from django.views.generic import ListView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from datetime import datetime, timedelta
from django.db import IntegrityError
import json
from appointments.models import Appointment

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

class AppointmentsListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    model = Appointment
    template_name = "appointments/list.html"
    context_object_name = "appointments"
    paginate_by = 10
    ordering = ["-created_at"]
    search_fields = ["title", "description"]
    filter_fields = ["status"]
    list_display = ["title", "description", "date", "time", "estimated_duration", "status"]
    list_filter = ["status"]
    login_url = '/login/'

    def test_func(self):
        return self.request.user.is_staff or self.request.user.is_superuser

@csrf_exempt
@require_http_methods(["POST"])
def create_appointment(request: HttpRequest):
    # if not request.get_host().endswith("bigaddict.shop"):
    #     return JsonResponse({"error": "Unauthorized"}, status=401)
    
    try:
        data = json.loads(request.body)
        title = data.get("title")
        description = data.get("description")
        date = data.get("date")
        time = data.get("time")
        estimated_duration = data.get("estimated_duration")
        status = data.get("status")
        email = data.get("email")
        phone = data.get("phone")
        full_name = data.get("full_name")
        appointment = Appointment.objects.create(title=title, description=description, date=date, time=time, estimated_duration=estimated_duration, status=status, email=email, phone=phone, full_name=full_name)
        return JsonResponse({"success": "Appointment created successfully"}, status=201)
    except IntegrityError as e:
        return JsonResponse({"error": "Email or phone already exists", "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

@csrf_exempt
@require_http_methods(["GET"])
def get_appointment(request: HttpRequest):
    try:
        data = json.loads(request.body)
        id = data.get("id", None)
        email = data.get("email", None)
        phone = data.get("phone", None)
        if not all([id, email, phone]):
            return JsonResponse({"error": "Missing required fields: id, email, and phone"}, status=400)
        appointment = Appointment.objects.get(id=id, email=email, phone=phone)
        return JsonResponse({"success": "Appointment fetched successfully", "appointment": appointment.to_dict()}, status=200)
    except Appointment.DoesNotExist:
        return JsonResponse({"error": "Appointment not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def check_availability(request: HttpRequest):
    try:
        data = json.loads(request.body)
        date_str = data.get("date")
        time_str = data.get("time")
        duration = data.get("duration")
        
        if not all([date_str, time_str, duration]):
            return JsonResponse({
                "error": "Missing required fields: date, time, and duration"
            }, status=400)
        
        try:
            duration = int(duration)
            if duration <= 0:
                raise ValueError("Duration must be positive")
        except (ValueError, TypeError):
            return JsonResponse({
                "error": "Duration must be a positive integer"
            }, status=400)
        
        try:
            appointment_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            appointment_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError as e:
            return JsonResponse({
                "error": f"Invalid date/time format. Use YYYY-MM-DD for date and HH:MM for time. {str(e)}"
            }, status=400)
        
        if appointment_date < datetime.now().date():
            return JsonResponse({
                "available": False,
                "message": "Cannot book appointments in the past",
                "requested_slot": {
                    "date": date_str,
                    "time": time_str,
                    "duration": duration
                }
            })
        
        start_datetime = datetime.combine(appointment_date, appointment_time)
        end_datetime = start_datetime + timedelta(minutes=duration)
        
        active_statuses = ['pending', 'confirmed', 'rescheduled']
        
        same_date_appointments = Appointment.objects.filter(
            date=appointment_date,
            status__in=active_statuses
        ).select_related().only('id', 'title', 'time', 'estimated_duration', 'status')
        
        conflicting_appointments = []
        
        for appointment in same_date_appointments:
            appointment_start = datetime.combine(appointment.date, appointment.time)
            appointment_end = appointment_start + timedelta(minutes=appointment.estimated_duration)
            
            overlap_start = max(start_datetime, appointment_start)
            overlap_end = min(end_datetime, appointment_end)
            
            if overlap_start < overlap_end:
                conflicting_appointments.append({
                    "id": appointment.id,
                    "time": appointment.time.strftime("%H:%M"),
                    "duration": appointment.estimated_duration,
                    "status": appointment.status,
                    "start_time": appointment_start.strftime("%Y-%m-%d %H:%M"),
                    "end_time": appointment_end.strftime("%Y-%m-%d %H:%M")
                })
        
        if conflicting_appointments:
            return JsonResponse({
                "available": False,
                "message": f"Time slot conflicts with {len(conflicting_appointments)} existing appointment(s)",
                "conflicting_appointments": conflicting_appointments,
                "requested_slot": {
                    "date": date_str,
                    "time": time_str,
                    "duration": duration,
                    "start_time": start_datetime.strftime("%Y-%m-%d %H:%M"),
                    "end_time": end_datetime.strftime("%Y-%m-%d %H:%M")
                }
            })
        
        return JsonResponse({
            "available": True,
            "message": "Time slot is available for booking",
            "requested_slot": {
                "date": date_str,
                "time": time_str,
                "duration": duration,
                "start_time": start_datetime.strftime("%Y-%m-%d %H:%M"),
                "end_time": end_datetime.strftime("%Y-%m-%d %H:%M")
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            "error": "Invalid JSON format"
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "error": f"An error occurred: {str(e)}"
        }, status=500)

@staff_member_required
def admin_manage_appointment(request, appointment_id):
    """
    Admin view to manage individual appointments.
    Allows editing title, description (with markdown), time, duration, and status.
    """
    appointment = get_object_or_404(Appointment, id=appointment_id)
    
    if request.method == 'POST':
        try:
            # Update appointment fields
            appointment.title = request.POST.get('title', appointment.title)
            appointment.description = request.POST.get('description', appointment.description)
            appointment.status = request.POST.get('status', appointment.status)
            
            # Handle date and time
            date_str = request.POST.get('date')
            time_str = request.POST.get('time')
            duration = request.POST.get('duration')
            
            if date_str:
                appointment.date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if time_str:
                appointment.time = datetime.strptime(time_str, '%H:%M').time()
            if duration:
                appointment.estimated_duration = int(duration)
            
            appointment.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Appointment updated successfully'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
    
    context = {
        'appointment': appointment,
        'status_choices': Appointment.APPOINTMENT_STATUS_CHOICES
    }
    
    return render(request, 'appointments/admin_manage.html', context)
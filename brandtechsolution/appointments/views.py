from django.views.generic import ListView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from datetime import datetime, timedelta
from django.db import IntegrityError
from django.db.models import Q
import json
import logging
from appointments.models import Appointment
from brandtechsolution import turnstile

logger = logging.getLogger(__name__)
from staff.decorators import capability_required

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
        user = self.request.user
        return user.is_staff and user.has_perm("staff.manage_appointments")

    def get_queryset(self):
        qs = super().get_queryset().order_by(*self.ordering)

        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(full_name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = (self.request.GET.get("q") or "").strip()
        context["status_filter"] = (self.request.GET.get("status") or "").strip()
        context["status_choices"] = Appointment.APPOINTMENT_STATUS_CHOICES
        return context

@csrf_exempt
@require_http_methods(["POST"])
def create_appointment(request: HttpRequest):
    # Before anything is parsed or written. This endpoint creates a row per
    # POST with no uniqueness left to slow anyone down (migration 0007
    # removed it deliberately), and every booking mails five people - so an
    # unprotected script here is both a full appointments table and a mail
    # flood.
    if not turnstile.passed(request):
        return JsonResponse({"error": turnstile.FAILED}, status=400)

    try:
        data = json.loads(request.body)
        title = data.get("title") or "Strategy Consultation"
        description = data.get("description") or "Booked via TekLora web consultation calendar."
        date = data.get("date")
        time = data.get("time")
        estimated_duration = data.get("estimated_duration") or 30
        email = (data.get("email") or "").strip()
        # Left empty when not supplied. This used to synthesise a plausible
        # +2547XXXXXXXX number to satisfy the unique phone constraint, which
        # put fabricated contact details in front of staff as though the
        # client had given them. The constraint is gone; an empty field is
        # honest about what we know.
        phone = (data.get("phone") or "").strip()
        full_name = (data.get("full_name") or data.get("name") or "Anonymous Client").strip()

        if not email or not date or not time:
            return JsonResponse({"error": "Missing required fields: email, date, and time"}, status=400)

        # Always a new row. This endpoint is public and unauthenticated, so a
        # submitted email address proves nothing about who is submitting it -
        # matching one against an existing booking and updating that booking
        # let anybody rewrite a stranger's appointment by knowing their
        # address. Repeat bookings are a real thing; staff dedupe them from
        # the appointments list.
        appointment = Appointment.objects.create(
            title=title,
            description=description,
            date=date,
            time=time,
            estimated_duration=estimated_duration,
            # Not `status` from the request body. A public caller could send
            # "confirmed" and have their booking show up to staff as already
            # agreed. Confirming is a staff decision, made in the panel.
            status="pending",
            email=email,
            phone=phone,
            full_name=full_name
        )

        # Notify whoever currently holds manage_appointments, rather than a
        # list of addresses compiled into this module. Enrolling a new team
        # member is a panel action; nobody has to remember to edit this.
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            from staff.emails import capability_holder_emails

            recipients = capability_holder_emails("manage_appointments")
            if not recipients:
                logger.warning(
                    "No manage_appointments holder has an email address; "
                    "appointment #%s saved with nobody notified.",
                    appointment.id,
                )
            send_mail(
                subject=f"New Strategy Session Booking: {title} ({full_name})",
                message=(
                    f"New Strategy Session Booking on Teklora:\n\n"
                    f"Client Name: {full_name}\n"
                    f"Client Email: {email}\n"
                    f"Client Phone: {phone or 'N/A'}\n"
                    f"Subject / Topic: {title}\n"
                    f"Date: {date}\n"
                    f"Time: {time}\n"
                    f"Estimated Duration: {estimated_duration} minutes\n\n"
                    f"Description / Notes:\n{description}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=True,
            )
        except Exception:
            # Best-effort: the booking is saved and shows in the appointments
            # list regardless. Logged rather than swallowed, because a silent
            # mail outage on a lead path is indistinguishable from no leads.
            logger.exception(
                "Could not send booking notification for appointment %s",
                appointment.id,
            )

        return JsonResponse({"success": "Appointment created successfully", "id": appointment.id}, status=201)
    except IntegrityError:
        # This endpoint is public, so its error bodies are public. Raw
        # exception text names tables, columns and constraints.
        logger.exception("create_appointment integrity error")
        return JsonResponse({"error": "Could not save the booking."}, status=400)
    except Exception:
        logger.exception("create_appointment failed")
        return JsonResponse({"error": "Could not save the booking."}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def get_appointment(request: HttpRequest):
    try:
        data = json.loads(request.body)
        id = data.get("id", None)
        email = data.get("email", None)
        phone = data.get("phone", None)
        if not all([id, email, phone]):
            return JsonResponse({"error": "Missing required fields: id, email, and phone"}, status=400)
        appointment = Appointment.objects.get(id=id, email=email, phone=phone)
        appointment_data = {
            "id": appointment.id,
            "email": appointment.email,
            "phone": appointment.phone,
            "full_name": appointment.full_name,
            "title": appointment.title,
            "description": appointment.description,
            "date": appointment.date.isoformat(),
            "time": appointment.time.strftime("%H:%M"),
            "estimated_duration": appointment.estimated_duration,
            "status": appointment.status,
            "created_at": appointment.created_at.isoformat(),
            "updated_at": appointment.updated_at.isoformat(),
        }
        return JsonResponse({"success": "Appointment fetched successfully", "appointment": appointment_data}, status=200)
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
        ).only('id', 'title', 'time', 'estimated_duration', 'status')
        
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

@capability_required("manage_appointments")
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
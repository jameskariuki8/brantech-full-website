import os
import re

original_path = r'd:\brantech-full-website-master\original_contacts.html'
current_path = r'd:\brantech-full-website-master\brandtechsolution\brand\templates\brand\contacts.html'

with open(original_path, 'r', encoding='utf-8') as f:
    orig = f.read()

with open(current_path, 'r', encoding='utf-8') as f:
    curr = f.read()

# Extract the calendar section
calendar_match = re.search(r'<!-- Book Strategy Consultation Section -->.*?</section>', orig, flags=re.DOTALL)
calendar_html = calendar_match.group(0) if calendar_match else ''

# Extract the JS
js_match = re.search(r'<!-- Interactive Features Script \(Vanilla JS\) -->.*', orig, flags=re.DOTALL)
js_html = js_match.group(0) if js_match else ''

# Extract modals
booking_modal_match = re.search(r'<!-- Interactive Booking Modal -->.*?</div>\s*</div>', orig, flags=re.DOTALL)
booking_modal = booking_modal_match.group(0) if booking_modal_match else ''

booking_success_match = re.search(r'<!-- Booking Success Modal Card -->.*?</div>\s*</div>', orig, flags=re.DOTALL)
booking_success = booking_success_match.group(0) if booking_success_match else ''


# Wrap calendar in a new modal
calendar_modal = f'''
<!-- Full Calendar Modal -->
<div id="calendarModal" class="fixed inset-0 z-[100] bg-black/80 backdrop-blur-md hidden flex items-center justify-center p-4 overflow-y-auto" onclick="if(event.target === this) closeCalendarModal()">
    <div class="clean-card max-w-5xl w-full p-2 sm:p-4 rounded-3xl border border-borderLight relative my-auto bg-surface overflow-y-auto shadow-2xl" style="max-height: 95vh;">
        <button type="button" onclick="closeCalendarModal()" class="absolute top-6 right-6 w-10 h-10 rounded-full bg-red-50 hover:bg-red-100 text-red-500 flex items-center justify-center text-sm z-50 transition-colors border border-red-200">
            <i class="fas fa-times"></i>
        </button>
        {calendar_html}
    </div>
</div>
'''

# We also need to add a button to open it. We can add this button below the contact form.
open_button_html = '''
<div class="mt-8 text-center pt-6 border-t border-borderLight">
    <p class="text-xs text-secondaryText mb-3">Or prefer to speak directly with an architect?</p>
    <button type="button" onclick="openCalendarModal()" class="btn-premium btn-premium-secondary py-3 px-6 rounded-xl font-bold text-xs sm:text-sm shadow-lg border border-borderLight flex items-center justify-center gap-2 w-full mx-auto sm:w-auto">
        <i class="fas fa-calendar-alt text-[#007AFF]"></i> Open Strategy Calendar
    </button>
</div>
'''

# Insert the open button after the form section in current html
curr = curr.replace('</form>\n                </div>', '</form>\n                </div>\n' + open_button_html)

# Add the modals and JS before </body>
additions = f'''
{calendar_modal}
{booking_modal}
{booking_success}

{js_html}
'''
curr = curr.replace('</body>', additions)

# Let's add the JS function to open/close the calendar modal
js_functions = '''
        function openCalendarModal() {
            document.getElementById('calendarModal').classList.remove('hidden');
        }
        function closeCalendarModal() {
            document.getElementById('calendarModal').classList.add('hidden');
        }
'''
# inject into js_html block
curr = curr.replace('// Booking Modal logic', js_functions + '\n        // Booking Modal logic')

with open(current_path, 'w', encoding='utf-8') as f:
    f.write(curr)

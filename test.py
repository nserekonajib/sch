# Run this in a Python console or as a one-off script
from supabase import create_client, Client
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def fix_student_balances(student_id, institute_id):
    """Fix invoice balances for a specific student"""
    
    # Get all invoices for this student
    invoices_response = supabase.table('invoices')\
        .select('*')\
        .eq('student_id', student_id)\
        .eq('institute_id', institute_id)\
        .execute()
    
    # Get all payments for this student
    payments_response = supabase.table('payments')\
        .select('*')\
        .eq('student_id', student_id)\
        .eq('institute_id', institute_id)\
        .execute()
    
    # Get all discounts for this student
    discounts_response = supabase.table('discounts')\
        .select('*')\
        .eq('student_id', student_id)\
        .eq('institute_id', institute_id)\
        .execute()
    
    all_payments = payments_response.data if payments_response.data else []
    all_discounts = discounts_response.data if discounts_response.data else []
    
    print(f"Fixing balances for student: {student_id}")
    print(f"Invoices found: {len(invoices_response.data)}")
    print(f"Payments found: {len(all_payments)}")
    print(f"Discounts found: {len(all_discounts)}")
    print("=" * 50)
    
    for invoice in invoices_response.data:
        # Find payments for this invoice
        inv_payments = [p for p in all_payments if p.get('invoice_id') == invoice['id']]
        total_paid = sum(float(p['amount']) for p in inv_payments)
        
        # Find discounts for this invoice
        inv_discounts = [d for d in all_discounts if d.get('invoice_id') == invoice['id']]
        total_discount = sum(float(d.get('discount_amount', 0)) for d in inv_discounts)
        
        # Calculate correct balance
        invoice_total = float(invoice['total_amount'])
        correct_balance = invoice_total - total_paid - total_discount
        
        # Don't show negative balance
        if correct_balance < 0:
            correct_balance = 0
        
        # Determine status
        if correct_balance == 0 and total_paid > 0:
            status = 'paid'
        elif correct_balance < invoice_total and total_paid > 0:
            status = 'partial'
        elif correct_balance == invoice_total:
            status = 'pending'
        else:
            status = 'pending'
        
        print(f"Invoice: {invoice['invoice_number']}")
        print(f"  Total: {invoice_total}")
        print(f"  Paid: {total_paid}")
        print(f"  Discount: {total_discount}")
        print(f"  Old Balance: {invoice.get('balance')}")
        print(f"  Correct Balance: {correct_balance}")
        print(f"  Status: {status}")
        print("-" * 30)
        
        # Update invoice with correct values
        supabase.table('invoices')\
            .update({
                'paid_amount': total_paid,
                'balance': correct_balance,
                'status': status,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', invoice['id'])\
            .eq('institute_id', institute_id)\
            .execute()

# Fix for SUDAIS JUMA
# Replace these with the actual IDs
student_id = "f33935ad-56cd-4b9b-a438-199d7ce85480"  # SUDAIS JUMA's UUID
institute_id = "777d546a-1b12-428e-a8e5-d21cb8a7d418"  # Your institute ID

fix_student_balances(student_id, institute_id)
print("Done!")
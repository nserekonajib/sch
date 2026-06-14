# process_bulk_payments.py
import pandas as pd
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
import uuid
import random
import string
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def generate_unique_receipt_number(institute_id, existing_numbers):
    """Generate unique receipt number"""
    max_attempts = 10
    attempts = 0
    
    while attempts < max_attempts:
        try:
            year = datetime.now().strftime('%Y')
            month = datetime.now().strftime('%m')
            
            random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            
            response = supabase.table('payments')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .gte('created_at', f"{year}-{month}-01")\
                .execute()
            
            count = (response.count or 0) + 1
            receipt_number = f"RCP-{year}{month}-{random_component}-{str(count).zfill(3)}"
            
            if receipt_number not in existing_numbers:
                return receipt_number
                
        except Exception as e:
            print(f"Error generating receipt number (attempt {attempts + 1}): {e}")
        
        attempts += 1
        import time
        time.sleep(0.1)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    fallback_number = f"RCP-{timestamp}"
    
    if fallback_number in existing_numbers:
        fallback_number = f"RCP-{timestamp}-{random.randint(1000, 9999)}"
    
    return fallback_number

def get_institute_id():
    """Get the first active institute ID"""
    try:
        response = supabase.table('institutes')\
            .select('id')\
            .limit(1)\
            .execute()
        
        if response.data:
            return response.data[0]['id']
        else:
            print("ERROR: No institute found in database")
            return None
    except Exception as e:
        print(f"ERROR getting institute ID: {e}")
        return None

def process_payment_for_student(institute_id, student_id, paid_amount):
    """Process a single student's payment using only student ID and amount"""
    try:
        print(f"\n[Processing] Student ID: {student_id}, Amount: UGX {paid_amount:,.0f}")
        
        # Find student by Student ID only
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        if not student_response.data:
            print(f"[FAILED] Student ID {student_id} not found in database")
            return {
                'success': False,
                'student_id': student_id,
                'error': 'Student not found'
            }
        
        student = student_response.data[0]
        student_name = student['name']
        print(f"[FOUND] {student_name}")
        
        # Get all invoices with balance > 0
        invoices_response = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student['id'])\
            .eq('institute_id', institute_id)\
            .gt('balance', 0)\
            .order('created_at', desc=False)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        if not invoices and paid_amount > 0:
            print(f"[INFO] No outstanding invoices - payment will be advance/credit")
        
        remaining_amount = paid_amount
        
        # Distribute payment to outstanding invoices
        for invoice in invoices:
            if remaining_amount <= 0:
                break
            
            payment_for_invoice = min(remaining_amount, invoice['balance'])
            
            if payment_for_invoice > 0:
                new_paid = invoice['paid_amount'] + payment_for_invoice
                new_balance = invoice['total_amount'] - new_paid
                new_status = 'paid' if new_balance == 0 else 'partial'
                
                # Update invoice
                supabase.table('invoices')\
                    .update({
                        'paid_amount': new_paid,
                        'balance': new_balance,
                        'status': new_status,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', invoice['id'])\
                    .eq('institute_id', institute_id)\
                    .execute()
                
                print(f"[PAID] UGX {payment_for_invoice:,.0f} to invoice {invoice['invoice_number']} (New balance: UGX {new_balance:,.0f})")
                remaining_amount -= payment_for_invoice
        
        # Handle remaining amount (overpayment)
        if remaining_amount > 0:
            print(f"[CREDIT] Overpayment of UGX {remaining_amount:,.0f} will be credit")
            
            # Get the most recent invoice
            recent_invoice_response = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if recent_invoice_response.data:
                invoice = recent_invoice_response.data[0]
                new_paid = invoice['paid_amount'] + remaining_amount
                new_balance = invoice['total_amount'] - new_paid
                new_status = 'credit' if new_balance < 0 else invoice['status']
                
                supabase.table('invoices')\
                    .update({
                        'paid_amount': new_paid,
                        'balance': new_balance,
                        'status': new_status,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', invoice['id'])\
                    .eq('institute_id', institute_id)\
                    .execute()
                
                print(f"[CREDIT] Applied to invoice {invoice['invoice_number']} (New credit: UGX {abs(new_balance):,.0f})")
            else:
                # Create new credit invoice
                new_invoice_id = str(uuid.uuid4())
                new_invoice_number = f"CREDIT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                invoice_data = {
                    'id': new_invoice_id,
                    'institute_id': institute_id,
                    'student_id': student['id'],
                    'invoice_number': new_invoice_number,
                    'total_amount': -remaining_amount,
                    'paid_amount': remaining_amount,
                    'balance': -remaining_amount,
                    'status': 'credit',
                    'due_date': (datetime.now() + timedelta(days=365)).date().isoformat(),
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                supabase.table('invoices').insert(invoice_data).execute()
                print(f"[CREDIT] Created new credit invoice: {new_invoice_number}")
        
        # Get existing receipt numbers
        existing_receipts_response = supabase.table('payments')\
            .select('receipt_number')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_numbers = set()
        if existing_receipts_response.data:
            for receipt in existing_receipts_response.data:
                existing_numbers.add(receipt['receipt_number'])
        
        # Generate receipt number
        receipt_number = generate_unique_receipt_number(institute_id, existing_numbers)
        
        # Create payment record
        payment_id = str(uuid.uuid4())
        payment_data = {
            'id': payment_id,
            'institute_id': institute_id,
            'student_id': student['id'],
            'amount': paid_amount,
            'payment_method': 'bulk_upload',
            'receipt_number': receipt_number,
            'payment_date': datetime.now().date().isoformat(),
            'fee_month': datetime.now().strftime('%Y-%m-01'),
            'notes': f'Bulk payment import',
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('payments').insert(payment_data).execute()
        
        # Get updated total balance
        updated_invoices = supabase.table('invoices')\
            .select('balance')\
            .eq('student_id', student['id'])\
            .eq('institute_id', institute_id)\
            .execute()
        
        total_due = sum(inv['balance'] for inv in updated_invoices.data)
        
        print(f"[SUCCESS] Receipt: {receipt_number}, Remaining: UGX {total_due:,.0f}")
        
        return {
            'success': True,
            'student_id': student_id,
            'student_name': student_name,
            'receipt_number': receipt_number,
            'amount_paid': paid_amount,
            'remaining_balance': total_due
        }
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'student_id': student_id,
            'error': str(e)
        }

def main():
    """Main function to process bulk payments from Excel file"""
    print("="*60)
    print("BULK PAYMENT PROCESSING SYSTEM")
    print("="*60)
    
    # Get institute ID
    institute_id = 'e355f1f4-d202-40d3-ad03-f27af2b11ad6'
    if not institute_id:
        print("ERROR: Could not retrieve institute ID")
        return
    
    print(f"Institute ID: {institute_id}")
    
    # Read Excel file
    excel_file = 'payments.xlsx'
    
    if not os.path.exists(excel_file):
        print(f"ERROR: File '{excel_file}' not found in current directory")
        print(f"Current directory: {os.getcwd()}")
        return
    
    try:
        # Read the Excel file
        df = pd.read_excel(excel_file)
        print(f"\nLoaded {len(df)} records from {excel_file}")
        
        # Display column names for verification
        print("\nColumns found in Excel:")
        for col in df.columns:
            print(f"  - {col}")
        
        # Filter for students with Paid Amount > 0
        # Note: Adjust column name if needed - could be 'Paid Amount' or 'Paid Amount (UGX)'
        paid_column = None
        for col in df.columns:
            if 'paid' in col.lower():
                paid_column = col
                break
        
        if not paid_column:
            print("ERROR: Could not find 'Paid Amount' column in Excel file")
            print("Available columns:", list(df.columns))
            return
        
        print(f"\nUsing '{paid_column}' as payment amount column")
        
        # Filter students with payment > 0
        paid_students = df[df[paid_column] > 0]
        
        if len(paid_students) == 0:
            print("\nNo students with paid amount > 0 found in the file")
            return
        
        print(f"\nFound {len(paid_students)} students with payments to process")
        
        # Find Student ID column
        student_id_column = None
        for col in df.columns:
            if 'student id' in col.lower() or 'student_id' in col.lower():
                student_id_column = col
                break
        
        if not student_id_column:
            print("ERROR: Could not find 'Student ID' column in Excel file")
            print("Available columns:", list(df.columns))
            return
        
        print(f"Using '{student_id_column}' as student ID column")
        
        # Process each student
        results = []
        successful = 0
        failed = 0
        
        for idx, row in paid_students.iterrows():
            student_id = str(row[student_id_column]).strip()
            paid_amount = float(row[paid_column])
            
            # Skip if student ID is empty or NaN
            if pd.isna(student_id) or student_id == 'nan' or not student_id:
                print(f"\n[SKIP] Row {idx + 1}: Invalid student ID")
                failed += 1
                continue
            
            result = process_payment_for_student(institute_id, student_id, paid_amount)
            results.append(result)
            
            if result['success']:
                successful += 1
            else:
                failed += 1
        
        # Print summary
        print("\n" + "="*60)
        print("PROCESSING SUMMARY")
        print("="*60)
        print(f"Total students processed: {len(paid_students)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        
        # Save detailed results to file (without Unicode characters)
        with open('payment_results.txt', 'w', encoding='utf-8') as f:
            f.write("BULK PAYMENT PROCESSING RESULTS\n")
            f.write("="*60 + "\n\n")
            
            f.write(f"SUCCESSFUL PAYMENTS ({successful}):\n")
            f.write("-"*60 + "\n")
            for result in results:
                if result['success']:
                    f.write(f"OK: {result['student_name']} (ID: {result['student_id']})\n")
                    f.write(f"    Receipt: {result['receipt_number']}\n")
                    f.write(f"    Amount: UGX {result['amount_paid']:,.0f}\n")
                    f.write(f"    Remaining Balance: UGX {result['remaining_balance']:,.0f}\n\n")
            
            f.write(f"\nFAILED PAYMENTS ({failed}):\n")
            f.write("-"*60 + "\n")
            for result in results:
                if not result['success']:
                    f.write(f"FAIL: Student ID: {result['student_id']}\n")
                    f.write(f"    Error: {result.get('error', 'Unknown error')}\n\n")
        
        print(f"\nDetailed results saved to 'payment_results.txt'")
        
        # Also save a simple CSV summary
        summary_data = []
        for result in results:
            summary_data.append({
                'Student ID': result['student_id'],
                'Student Name': result.get('student_name', 'N/A'),
                'Status': 'Success' if result['success'] else 'Failed',
                'Amount Paid': result.get('amount_paid', 0),
                'Receipt Number': result.get('receipt_number', 'N/A'),
                'Remaining Balance': result.get('remaining_balance', 0),
                'Error': result.get('error', '')
            })
        
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_csv('payment_summary.csv', index=False)
        print(f"CSV summary saved to 'payment_summary.csv'")
        
    except Exception as e:
        print(f"ERROR reading Excel file: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
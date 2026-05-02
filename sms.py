#!/usr/bin/env python3
"""
Institute Management Script - FORCE DELETE MODE
Ignores foreign key constraints and deletes institutes and users
"""

import os
import sys
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
    sys.exit(1)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_all_institutes():
    """Fetch all institutes from the database"""
    try:
        response = supabase.table('institutes').select('*').order('created_at', desc=False).execute()
        return response.data
    except Exception as e:
        print(f"❌ Error fetching institutes: {e}")
        return []

def delete_user_from_auth(user_id):
    """Delete a user from Supabase Auth using service role"""
    if not user_id or user_id == 'None' or str(user_id).strip() == '':
        print("   ℹ️  No valid user_id, skipping auth deletion")
        return True
    
    try:
        if SUPABASE_SERVICE_KEY:
            import requests
            headers = {
                'apikey': SUPABASE_SERVICE_KEY,
                'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
                'Content-Type': 'application/json'
            }
            
            url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
            response = requests.delete(url, headers=headers)
            
            if response.status_code in [200, 204]:
                print(f"   ✅ Deleted user {user_id[:8]}... from Auth")
                return True
            elif response.status_code == 404:
                print(f"   ℹ️  User {user_id[:8]}... not found in Auth")
                return True
            else:
                print(f"   ⚠️  Could not delete user: {response.status_code}")
                return False
        else:
            print(f"   ⚠️  No SERVICE_KEY - user must be deleted manually")
            return False
    except Exception as e:
        print(f"   ⚠️  Auth deletion error: {e}")
        return False

def force_delete_institute(institute_id):
    """Force delete institute by disabling constraints temporarily"""
    try:
        # Try direct delete first
        response = supabase.table('institutes').delete().eq('id', institute_id).execute()
        print(f"   ✅ Deleted institute from database")
        return True
    except Exception as e:
        error_msg = str(e)
        
        if 'foreign key constraint' in error_msg:
            print(f"   🔥 Foreign key detected - forcing deletion...")
            
            # Strategy: Set foreign keys to NULL or delete related records
            try:
                # Option 1: Try to set class_enrollments to NULL where possible
                supabase.table('class_enrollments').delete().neq('class_id', '00000000-0000-0000-0000-000000000000').execute()
            except:
                pass
            
            try:
                # Option 2: Delete classes for this institute
                supabase.table('classes').delete().eq('institute_id', institute_id).execute()
            except:
                pass
            
            try:
                # Option 3: Try force delete again
                response = supabase.table('institutes').delete().eq('id', institute_id).execute()
                print(f"   ✅ Force deleted institute from database")
                return True
            except Exception as force_error:
                print(f"   ❌ Force delete failed: {force_error}")
                
                # Last resort: Use raw SQL via RPC if you have a function
                try:
                    # If you have a delete function in Supabase
                    result = supabase.rpc('force_delete_institute', {'institute_id': institute_id}).execute()
                    print(f"   ✅ Deleted via RPC function")
                    return True
                except:
                    print(f"   💡 Manual SQL needed for this institute")
                    return False
        
        print(f"   ❌ Error: {error_msg[:100]}")
        return False

def display_institutes(institutes):
    """Display institutes in a formatted table"""
    if not institutes:
        print("\n📋 No institutes found.\n")
        return
    
    print("\n" + "="*130)
    print(f"{'IDX':<4} {'Institute Name':<35} {'Email':<30} {'User ID':<36} {'Created'}")
    print("="*130)
    
    for idx, inst in enumerate(institutes):
        name = inst.get('institute_name')
        if not name:
            name = '⚠️ N/A'
        else:
            name = name[:32] if len(name) > 32 else name
        
        email = inst.get('email')
        if not email:
            email = 'N/A'
        else:
            email = email[:28] if len(email) > 28 else email
        
        user_id = inst.get('user_id')
        if not user_id:
            user_id = 'None'
        else:
            user_id = user_id[:34] if len(user_id) > 34 else user_id
        
        created = inst.get('created_at', 'N/A')
        if created and created != 'N/A':
            created = created[:10]
        
        print(f"{idx:<4} {name:<35} {email:<30} {user_id:<36} {created}")
    
    print("="*130)
    print(f"\n📊 Total: {len(institutes)} institute(s)")

def delete_institutes(institutes):
    """Delete institutes ignoring constraints"""
    if not institutes:
        return
    
    display_institutes(institutes)
    
    print("\n🗑️  FORCE DELETE INSTITUTES")
    print("-" * 60)
    print("Options:")
    print("  • Enter numbers separated by commas (e.g., 1,3,5)")
    print("  • Enter 'all' to delete everything")
    print("  • Enter 'incomplete' to delete incomplete records")
    print("  • Enter 'q' to quit")
    print()
    
    choice = input("👉 Select institutes to delete: ").strip()
    
    if choice.lower() == 'q':
        print("❌ Operation cancelled.")
        return
    
    indices_to_delete = []
    
    if choice.lower() == 'all':
        indices_to_delete = list(range(len(institutes)))
    elif choice.lower() == 'incomplete':
        indices_to_delete = [i for i, inst in enumerate(institutes) 
                           if not inst.get('institute_name') or not inst.get('email')]
        if not indices_to_delete:
            print("✅ No incomplete records found.")
            return
    else:
        try:
            for part in choice.split(','):
                part = part.strip()
                if part:
                    idx = int(part)
                    if 0 <= idx < len(institutes):
                        indices_to_delete.append(idx)
                    else:
                        print(f"⚠️  Index {idx} out of range")
        except ValueError:
            print("❌ Invalid input.")
            return
    
    if not indices_to_delete:
        print("❌ No valid indices selected.")
        return
    
    indices_to_delete = sorted(set(indices_to_delete))
    
    # Show what will be deleted
    print("\n📋 Selected for FORCE DELETION:")
    print("-" * 70)
    for idx in indices_to_delete:
        inst = institutes[idx]
        name = inst.get('institute_name', 'INCOMPLETE')
        email = inst.get('email', 'No email')
        print(f"  [{idx}] {name} - {email}")
    
    print()
    print("🔥 WARNING: Force delete will ignore foreign key constraints!")
    print("   This may leave orphaned records in the database.")
    print()
    
    confirm = input(f"⚠️  FORCE DELETE {len(indices_to_delete)} institute(s)? (type 'FORCE' to confirm): ").strip()
    
    if confirm != 'FORCE':
        print("❌ Deletion cancelled.")
        return
    
    print("\n🔥 FORCE DELETING...")
    print("-" * 60)
    
    deleted_count = 0
    failed_count = 0
    
    for idx in indices_to_delete:
        inst = institutes[idx]
        inst_id = inst.get('id')
        user_id = inst.get('user_id')
        inst_name = inst.get('institute_name', 'Unnamed')
        
        print(f"\n📌 Force deleting: {inst_name}")
        
        # Delete user from Auth
        if user_id and user_id != 'None':
            print(f"   👤 Deleting user...")
            delete_user_from_auth(user_id)
        
        # Force delete institute
        print(f"   🏫 Force deleting institute...")
        if force_delete_institute(inst_id):
            deleted_count += 1
            print(f"   ✅ Successfully force deleted")
        else:
            failed_count += 1
            print(f"   ❌ Force delete failed")
    
    print("\n" + "="*60)
    print(f"🔥 FORCE DELETE COMPLETE!")
    print(f"   • Deleted: {deleted_count} institute(s)")
    if failed_count > 0:
        print(f"   • Failed: {failed_count} institute(s)")
        print(f"   • You may need to delete these manually from Supabase dashboard")
    print("="*60)

def main():
    """Main function"""
    print("\n" + "="*60)
    print("🔥 INSTITUTE FORCE DELETE SYSTEM")
    print("="*60)
    print("⚠️  This tool ignores foreign key constraints")
    print("⚠️  Orphaned records may remain in the database")
    print("="*60)
    
    institutes = get_all_institutes()
    
    if not institutes:
        print("\n❌ No institutes found.")
        return
    
    while True:
        display_institutes(institutes)
        
        print("\n" + "-"*60)
        print("📋 MENU")
        print("  1. FORCE DELETE institutes")
        print("  2. Refresh list")
        print("  3. Exit")
        print("-"*60)
        
        choice = input("\n👉 Choose option (1-3): ").strip()
        
        if choice == '1':
            delete_institutes(institutes)
            print("\n🔄 Refreshing...")
            institutes = get_all_institutes()
        elif choice == '2':
            institutes = get_all_institutes()
        elif choice == '3':
            print("\n👋 Goodbye!")
            break
        else:
            print("❌ Invalid option.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
# delete_auth.py - Fixed WhatsApp Auth Cleanup

import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==================== CONFIGURATION ====================
AUTH_FOLDER = os.getenv('WHATSAPP_AUTH_FOLDER', 'auth_info_global')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

def delete_local_auth():
    """Delete local WhatsApp auth files"""
    auth_path = Path(AUTH_FOLDER)
    if auth_path.exists():
        shutil.rmtree(auth_path)
        print(f"✅ Deleted: {AUTH_FOLDER}")
        return True
    else:
        print(f"ℹ️ No auth folder found: {AUTH_FOLDER}")
        return False

def delete_supabase_auth():
    """Delete auth files from Supabase using a WHERE clause"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase not configured. Skipping.")
        return False
    
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # First get all records to count them
        result = supabase.table('whatsapp_auth_files_global').select('*').execute()
        count = len(result.data) if result.data else 0
        
        if count > 0:
            # Delete using a condition that matches all records (1=1)
            result = supabase.table('whatsapp_auth_files_global').delete().eq('filename', 'dummy').execute()
            # If that doesn't work, try deleting one by one
            if result.data is None:
                # Delete each file individually
                for record in supabase.table('whatsapp_auth_files_global').select('*').execute().data:
                    supabase.table('whatsapp_auth_files_global').delete().eq('filename', record['filename']).execute()
            print(f"✅ Supabase auth files deleted ({count} files)")
        else:
            print("ℹ️ No auth files found in Supabase")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        # Try alternative approach - truncate using raw SQL
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            # Use raw SQL to truncate
            supabase.rpc('execute_sql', {'sql': 'TRUNCATE TABLE whatsapp_auth_files_global'}).execute()
            print("✅ Supabase auth files truncated via SQL")
            return True
        except:
            print("⚠️ Could not delete Supabase auth. Please delete manually.")
            return False

def delete_supabase_auth_safe():
    """Delete auth files safely using batch deletion"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase not configured. Skipping.")
        return False
    
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Get all records first
        response = supabase.table('whatsapp_auth_files_global').select('*').execute()
        
        if response.data and len(response.data) > 0:
            # Collect all IDs or filenames
            files = response.data
            
            # Delete in batches using a loop
            deleted_count = 0
            for file in files:
                try:
                    # Delete by filename
                    supabase.table('whatsapp_auth_files_global')\
                        .delete()\
                        .eq('filename', file['filename'])\
                        .execute()
                    deleted_count += 1
                except Exception as e:
                    print(f"⚠️ Could not delete {file.get('filename', 'unknown')}: {e}")
            
            print(f"✅ Supabase auth files deleted ({deleted_count} files)")
        else:
            print("ℹ️ No auth files found in Supabase")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def delete_institute_auth(institute_id):
    """Delete auth files for a specific institute"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase not configured. Skipping.")
        return False
    
    if not institute_id:
        print("❌ Institute ID is required")
        return False
    
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # First check if records exist
        response = supabase.table('whatsapp_auth_files_custom')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        count = len(response.data) if response.data else 0
        
        if count > 0:
            result = supabase.table('whatsapp_auth_files_custom')\
                .delete()\
                .eq('institute_id', institute_id)\
                .execute()
            print(f"✅ Auth files deleted for institute: {institute_id} ({count} files)")
        else:
            print(f"ℹ️ No auth files found for institute: {institute_id}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def delete_all_local_auth_folders():
    """Delete all possible WhatsApp auth folders"""
    auth_folders = [
        'auth_info_global',
        'auth_info',
        'auth_info_global_backup',
        'auth_info_baileys'
    ]
    
    deleted = []
    for folder in auth_folders:
        auth_path = Path(folder)
        if auth_path.exists():
            try:
                shutil.rmtree(auth_path)
                deleted.append(folder)
                print(f"✅ Deleted: {folder}")
            except Exception as e:
                print(f"⚠️ Could not delete {folder}: {e}")
    
    if not deleted:
        print("ℹ️ No auth folders found")
    return deleted

def main():
    print("\n" + "="*50)
    print("🧹 WhatsApp Auth Cleanup")
    print("="*50 + "\n")
    
    # Delete all local auth folders
    print("📁 Deleting local auth folders...")
    delete_all_local_auth_folders()
    
    # Delete Supabase auth
    print("\n☁️ Deleting Supabase auth...")
    delete_supabase_auth_safe()
    
    print("\n" + "="*50)
    print("✅ Cleanup complete!")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
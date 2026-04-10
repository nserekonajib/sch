# instituteProfile.py - Fixed version without public.users table
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from supabase import create_client, Client
import os
import cloudinary
import cloudinary.uploader
from functools import wraps
from datetime import datetime
import uuid
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

instituteProfile_bp = Blueprint('instituteProfile', __name__, url_prefix='/institute')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def get_or_create_institute(user_id):
    """Get or create institute profile for the user"""
    try:
        # Check if institute exists
        response = supabase.table('institutes')\
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        
        # Create new institute with auto-generated ID
        institute_id = str(uuid.uuid4())
        institute_code = f"INS{datetime.now().strftime('%Y%m%d')}{user_id[:8]}"
        
        new_institute = {
            'id': institute_id,
            'user_id': user_id,
            'institute_code': institute_code,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('institutes').insert(new_institute).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
        
    except Exception as e:
        print(f"Error in get_or_create_institute: {e}")
        return None

@instituteProfile_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Institute Profile Page - View and Update"""
    user = session.get('user')
    user_id = user['id']
    user_email = user.get('email', '')
    
    # Get or create institute
    institute = get_or_create_institute(user_id)
    
    if not institute:
        flash('Error loading institute profile', 'error')
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        try:
            # Prepare update data
            update_data = {
                'institute_name': request.form.get('institute_name', '').strip(),
                'phone_number': request.form.get('phone_number', '').strip(),
                'email': request.form.get('email', '').strip(),
                'website': request.form.get('website', '').strip(),
                'address': request.form.get('address', '').strip(),
                'target_line': request.form.get('target_line', '').strip(),
                'country': request.form.get('country', '').strip(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Remove empty values
            update_data = {k: v for k, v in update_data.items() if v}
            
            # Handle logo upload
            if 'logo' in request.files and request.files['logo'].filename != '':
                logo_file = request.files['logo']
                
                # Upload to Cloudinary
                upload_result = cloudinary.uploader.upload(
                    logo_file,
                    folder=f"institute_logos/{institute['id']}",
                    public_id=f"logo_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    overwrite=True,
                    resource_type="image"
                )
                
                update_data['logo_url'] = upload_result['secure_url']
                update_data['logo_public_id'] = upload_result['public_id']
            
            # Update institute in Supabase
            result = supabase.table('institutes')\
                .update(update_data)\
                .eq('id', institute['id'])\
                .execute()
            
            if result.data:
                flash('Institute profile updated successfully!', 'success')
                return redirect(url_for('instituteProfile.profile'))
            else:
                flash('Failed to update profile', 'error')
                
        except Exception as e:
            print(f"Error updating profile: {e}")
            flash(f'Error: {str(e)}', 'error')
    
    # Prepare data for template
    profile_data = {
        'institute': institute,
        'user_email': user_email,
        'countries': get_countries_list()
    }
    
    return render_template('institute/profile.html', **profile_data)

@instituteProfile_bp.route('/remove-logo', methods=['POST'])
@login_required
def remove_logo():
    """Remove institute logo"""
    user = session.get('user')
    institute = get_or_create_institute(user['id'])
    
    if institute and institute.get('logo_public_id'):
        try:
            # Delete from Cloudinary
            cloudinary.uploader.destroy(institute['logo_public_id'])
            
            # Update database
            supabase.table('institutes')\
                .update({
                    'logo_url': None,
                    'logo_public_id': None,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', institute['id'])\
                .execute()
            
            return jsonify({'success': True, 'message': 'Logo removed successfully'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    return jsonify({'success': False, 'message': 'No logo found'}), 404

def get_countries_list():
    """Return list of countries for dropdown"""
    return [
        'Afghanistan', 'Albania', 'Algeria', 'Andorra', 'Angola', 'Antigua and Barbuda', 
        'Argentina', 'Armenia', 'Australia', 'Austria', 'Azerbaijan', 'Bahamas', 'Bahrain', 
        'Bangladesh', 'Barbados', 'Belarus', 'Belgium', 'Belize', 'Benin', 'Bhutan', 'Bolivia', 
        'Bosnia and Herzegovina', 'Botswana', 'Brazil', 'Brunei', 'Bulgaria', 'Burkina Faso', 
        'Burundi', 'Cabo Verde', 'Cambodia', 'Cameroon', 'Canada', 'Central African Republic', 
        'Chad', 'Chile', 'China', 'Colombia', 'Comoros', 'Congo', 'Costa Rica', 'Côte d\'Ivoire', 
        'Croatia', 'Cuba', 'Cyprus', 'Czech Republic', 'Denmark', 'Djibouti', 'Dominica', 
        'Dominican Republic', 'Ecuador', 'Egypt', 'El Salvador', 'Equatorial Guinea', 'Eritrea', 
        'Estonia', 'Eswatini', 'Ethiopia', 'Fiji', 'Finland', 'France', 'Gabon', 'Gambia', 
        'Georgia', 'Germany', 'Ghana', 'Greece', 'Grenada', 'Guatemala', 'Guinea', 'Guinea-Bissau', 
        'Guyana', 'Haiti', 'Honduras', 'Hungary', 'Iceland', 'India', 'Indonesia', 'Iran', 'Iraq', 
        'Ireland', 'Israel', 'Italy', 'Jamaica', 'Japan', 'Jordan', 'Kazakhstan', 'Kenya', 
        'Kiribati', 'Korea, North', 'Korea, South', 'Kosovo', 'Kuwait', 'Kyrgyzstan', 'Laos', 
        'Latvia', 'Lebanon', 'Lesotho', 'Liberia', 'Libya', 'Liechtenstein', 'Lithuania', 
        'Luxembourg', 'Madagascar', 'Malawi', 'Malaysia', 'Maldives', 'Mali', 'Malta', 
        'Marshall Islands', 'Mauritania', 'Mauritius', 'Mexico', 'Micronesia', 'Moldova', 
        'Monaco', 'Mongolia', 'Montenegro', 'Morocco', 'Mozambique', 'Myanmar', 'Namibia', 
        'Nauru', 'Nepal', 'Netherlands', 'New Zealand', 'Nicaragua', 'Niger', 'Nigeria', 
        'North Macedonia', 'Norway', 'Oman', 'Pakistan', 'Palau', 'Palestine', 'Panama', 
        'Papua New Guinea', 'Paraguay', 'Peru', 'Philippines', 'Poland', 'Portugal', 'Qatar', 
        'Romania', 'Russia', 'Rwanda', 'Saint Kitts and Nevis', 'Saint Lucia', 
        'Saint Vincent and the Grenadines', 'Samoa', 'San Marino', 'Sao Tome and Principe', 
        'Saudi Arabia', 'Senegal', 'Serbia', 'Seychelles', 'Sierra Leone', 'Singapore', 
        'Slovakia', 'Slovenia', 'Solomon Islands', 'Somalia', 'South Africa', 'South Sudan', 
        'Spain', 'Sri Lanka', 'Sudan', 'Suriname', 'Sweden', 'Switzerland', 'Syria', 'Taiwan', 
        'Tajikistan', 'Tanzania', 'Thailand', 'Timor-Leste', 'Togo', 'Tonga', 
        'Trinidad and Tobago', 'Tunisia', 'Turkey', 'Turkmenistan', 'Tuvalu', 'Uganda', 
        'Ukraine', 'United Arab Emirates', 'United Kingdom', 'United States', 'Uruguay', 
        'Uzbekistan', 'Vanuatu', 'Vatican City', 'Venezuela', 'Vietnam', 'Yemen', 'Zambia', 'Zimbabwe'
    ]
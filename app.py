import streamlit as st
import dropbox
from dropbox.exceptions import AuthError, ApiError
from dropbox.files import WriteMode, CommitInfo, UploadSessionStartResult
import os
import tempfile
import time
import datetime
import json
import uuid
import mimetypes
import pandas as pd
import io
import base64
from PIL import Image
import hashlib
import re

# Set page configuration
st.set_page_config(
    page_title="Advanced Dropbox Uploader",
    page_icon="📤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state variables
if 'upload_history' not in st.session_state:
    st.session_state.upload_history = []
if 'current_folder' not in st.session_state:
    st.session_state.current_folder = ""
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'dbx_client' not in st.session_state:
    st.session_state.dbx_client = None
if 'settings' not in st.session_state:
    st.session_state.settings = {
        "max_file_size_mb": 500,
        "allowed_extensions": "*",
        "chunk_size": 4 * 1024 * 1024,  # 4MB chunks for large file uploads
        "create_folders_if_not_exist": True,
        "overwrite_existing": True,
        "save_credentials": False
    }

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E88E5;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #0D47A1;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }
    .success-box {
        background-color: #E8F5E9;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 5px solid #4CAF50;
    }
    .warning-box {
        background-color: #FFF8E1;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 5px solid #FFC107;
    }
    .error-box {
        background-color: #FFEBEE;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 5px solid #F44336;
    }
    .info-box {
        background-color: #E3F2FD;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 5px solid #2196F3;
    }
    .stButton>button {
        width: 100%;
    }
    .folder-item {
        cursor: pointer;
        padding: 0.5rem;
        border-radius: 0.3rem;
    }
    .folder-item:hover {
        background-color: #E3F2FD;
    }
    .file-preview {
        border: 1px solid #BDBDBD;
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .dropbox-logo {
        max-width: 40px;
        margin-right: 10px;
        vertical-align: middle;
    }
    .footer {
        margin-top: 3rem;
        text-align: center;
        color: #757575;
    }
    .settings-section {
        background-color: #F5F5F5;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .history-item {
        padding: 0.5rem;
        border-bottom: 1px solid #EEEEEE;
    }
    .history-item:hover {
        background-color: #F5F5F5;
    }
    .auth-status {
        padding: 0.5rem;
        border-radius: 0.3rem;
        margin-bottom: 1rem;
    }
    .auth-connected {
        background-color: #E8F5E9;
        border-left: 3px solid #4CAF50;
    }
    .auth-disconnected {
        background-color: #FFEBEE;
        border-left: 3px solid #F44336;
    }
</style>
""", unsafe_allow_html=True)

# Utility functions
def format_size(size_bytes):
    """Format file size from bytes to human-readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def get_file_icon(file_name):
    """Return an appropriate icon based on file extension"""
    ext = os.path.splitext(file_name)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
        return "🖼️"
    elif ext in ['.pdf']:
        return "📄"
    elif ext in ['.doc', '.docx']:
        return "📝"
    elif ext in ['.xls', '.xlsx']:
        return "📊"
    elif ext in ['.ppt', '.pptx']:
        return "📽️"
    elif ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
        return "🗜️"
    elif ext in ['.mp3', '.wav', '.ogg', '.flac']:
        return "🎵"
    elif ext in ['.mp4', '.avi', '.mov', '.wmv']:
        return "🎬"
    elif ext in ['.txt', '.md', '.csv']:
        return "📋"
    elif ext in ['.py', '.js', '.html', '.css', '.java', '.cpp']:
        return "💻"
    else:
        return "📁"

def is_valid_file_type(file_name):
    """Check if file type is allowed based on settings"""
    if st.session_state.settings["allowed_extensions"] == "*":
        return True
    
    ext = os.path.splitext(file_name)[1].lower()
    allowed_extensions = st.session_state.settings["allowed_extensions"].split(',')
    allowed_extensions = [ext.strip().lower() for ext in allowed_extensions]
    
    return ext in allowed_extensions

def is_valid_file_size(file_size):
    """Check if file size is within the allowed limit"""
    max_size_bytes = st.session_state.settings["max_file_size_mb"] * 1024 * 1024
    return file_size <= max_size_bytes

def get_file_hash(file_content):
    """Generate a hash of file content for deduplication"""
    return hashlib.md5(file_content).hexdigest()

def normalize_path(path):
    """Ensure path starts with / and has no double slashes"""
    if not path:
        return "/"
    
    path = path.replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    
    # Remove double slashes
    while "//" in path:
        path = path.replace("//", "/")
    
    return path

def get_mime_type(file_name):
    """Get MIME type of a file"""
    mime_type, _ = mimetypes.guess_type(file_name)
    if mime_type is None:
        return "application/octet-stream"
    return mime_type

def can_preview(file_name):
    """Check if file can be previewed"""
    ext = os.path.splitext(file_name)[1].lower()
    previewable_extensions = [
        '.jpg', '.jpeg', '.png', '.gif', '.bmp',
        '.txt', '.md', '.csv', '.json'
    ]
    return ext in previewable_extensions

def generate_file_preview(file):
    """Generate a preview for supported file types"""
    file_content = file.getvalue()
    file_ext = os.path.splitext(file.name)[1].lower()
    
    if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
        try:
            image = Image.open(io.BytesIO(file_content))
            # Resize large images for preview
            max_width = 300
            if image.width > max_width:
                ratio = max_width / image.width
                new_height = int(image.height * ratio)
                image = image.resize((max_width, new_height))
            
            buffered = io.BytesIO()
            image.save(buffered, format=image.format)
            img_str = base64.b64encode(buffered.getvalue()).decode()
            return f'<img src="data:image/{image.format.lower()};base64,{img_str}" style="max-width:100%;">'
        except Exception as e:
            return f"<p>Error generating image preview: {str(e)}</p>"
    
    elif file_ext in ['.txt', '.md', '.json']:
        try:
            text_content = file_content.decode('utf-8')
            # Limit preview to first 500 characters
            if len(text_content) > 500:
                text_content = text_content[:500] + "..."
            return f'<pre style="background-color:#f5f5f5;padding:10px;border-radius:5px;max-height:200px;overflow:auto;">{text_content}</pre>'
        except Exception as e:
            return f"<p>Error generating text preview: {str(e)}</p>"
    
    elif file_ext in ['.csv']:
        try:
            df = pd.read_csv(io.BytesIO(file_content))
            # Limit preview to first 5 rows
            preview_df = df.head(5)
            return f'<div style="max-height:200px;overflow:auto;">{preview_df.to_html(index=False)}</div>'
        except Exception as e:
            return f"<p>Error generating CSV preview: {str(e)}</p>"
    
    return "<p>No preview available for this file type.</p>"

def add_to_upload_history(file_name, file_size, target_path, status, error_message=None):
    """Add an entry to the upload history"""
    history_entry = {
        "id": str(uuid.uuid4()),
        "file_name": file_name,
        "file_size": format_size(file_size),
        "target_path": target_path,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "error_message": error_message
    }
    st.session_state.upload_history.insert(0, history_entry)
    # Keep only the last 100 entries
    if len(st.session_state.upload_history) > 100:
        st.session_state.upload_history = st.session_state.upload_history[:100]

def save_settings():
    """Save current settings to session state"""
    st.session_state.settings["max_file_size_mb"] = max_file_size_mb
    st.session_state.settings["allowed_extensions"] = allowed_extensions
    st.session_state.settings["create_folders_if_not_exist"] = create_folders_if_not_exist
    st.session_state.settings["overwrite_existing"] = overwrite_existing
    st.session_state.settings["save_credentials"] = save_credentials
    st.success("Settings saved successfully!")

def clear_upload_history():
    """Clear the upload history"""
    st.session_state.upload_history = []
    st.success("Upload history cleared!")

def logout():
    """Log out from Dropbox"""
    st.session_state.authenticated = False
    st.session_state.dbx_client = None
    st.session_state.current_folder = ""
    st.success("Logged out successfully!")

# Dropbox API functions
def get_dropbox_client(app_key, app_secret, refresh_token):
    """Authenticate with Dropbox and return a client instance"""
    try:
        dbx = dropbox.Dropbox(
            app_key=app_key,
            app_secret=app_secret,
            oauth2_refresh_token=refresh_token
        )
        # Test the connection
        dbx.users_get_current_account()
        st.session_state.authenticated = True
        st.session_state.dbx_client = dbx
        return dbx
    except AuthError as e:
        st.error(f"Authentication failed: {e}")
        st.session_state.authenticated = False
        st.session_state.dbx_client = None
        return None
    except Exception as e:
        st.error(f"Error connecting to Dropbox: {e}")
        st.session_state.authenticated = False
        st.session_state.dbx_client = None
        return None

def list_folder(dbx, path):
    """List contents of a Dropbox folder"""
    try:
        result = dbx.files_list_folder(path)
        return result.entries
    except ApiError as e:
        if e.error.is_path() and e.error.get_path().is_not_found():
            st.warning(f"Folder not found: {path}")
        else:
            st.error(f"Error listing folder: {e}")
        return []
    except Exception as e:
        st.error(f"Error listing folder: {e}")
        return []

def create_folder(dbx, path):
    """Create a new folder in Dropbox"""
    try:
        dbx.files_create_folder_v2(path)
        return True
    except ApiError as e:
        if e.error.is_path() and e.error.get_path().is_conflict():
            # Folder already exists, which is fine
            return True
        else:
            st.error(f"Error creating folder: {e}")
            return False
    except Exception as e:
        st.error(f"Error creating folder: {e}")
        return False

def ensure_folder_exists(dbx, path):
    """Ensure that a folder exists, creating it and parent folders if needed"""
    if path == "/" or not path:
        return True
    
    # Split the path into components
    components = path.split("/")
    components = [c for c in components if c]
    
    current_path = ""
    for component in components:
        current_path += f"/{component}"
        if not create_folder(dbx, current_path):
            return False
    
    return True

def upload_small_file(dbx, file_content, target_path, overwrite=True):
    """Upload a small file (< 150MB) to Dropbox"""
    try:
        mode = WriteMode.overwrite if overwrite else WriteMode.add
        result = dbx.files_upload(
            file_content,
            target_path,
            mode=mode
        )
        return True, None
    except ApiError as e:
        error_msg = str(e)
        return False, error_msg
    except Exception as e:
        error_msg = str(e)
        return False, error_msg

def upload_large_file(dbx, file_content, target_path, chunk_size, overwrite=True):
    """Upload a large file (>= 150MB) to Dropbox using chunked upload"""
    try:
        file_size = len(file_content)
        
        # Start the upload session
        cursor = dropbox.files.UploadSessionCursor(
            session_id=dbx.files_upload_session_start(file_content[:chunk_size]).session_id,
            offset=chunk_size
        )
        
        # Upload the file in chunks
        for i in range(chunk_size, file_size, chunk_size):
            end = min(i + chunk_size, file_size)
            
            # If this is the last chunk, commit the upload
            if end == file_size:
                mode = WriteMode.overwrite if overwrite else WriteMode.add
                commit_info = CommitInfo(path=target_path, mode=mode)
                dbx.files_upload_session_finish(
                    file_content[i:end],
                    cursor,
                    commit_info
                )
            else:
                # Otherwise, continue the upload session
                dbx.files_upload_session_append_v2(
                    file_content[i:end],
                    cursor
                )
                cursor.offset = end
        
        return True, None
    except ApiError as e:
        error_msg = str(e)
        return False, error_msg
    except Exception as e:
        error_msg = str(e)
        return False, error_msg

def upload_to_dropbox(dbx, file, target_path, settings):
    """Upload a file to Dropbox with progress tracking and error handling"""
    try:
        file_content = file.getvalue()
        file_size = len(file_content)
        
        # Check if parent folder exists and create if needed
        parent_folder = os.path.dirname(target_path)
        if settings["create_folders_if_not_exist"] and parent_folder:
            if not ensure_folder_exists(dbx, parent_folder):
                return False, "Failed to create parent folders"
        
        # Choose upload method based on file size
        if file_size < 150 * 1024 * 1024:  # 150MB
            success, error_msg = upload_small_file(
                dbx, 
                file_content, 
                target_path, 
                settings["overwrite_existing"]
            )
        else:
            success, error_msg = upload_large_file(
                dbx, 
                file_content, 
                target_path, 
                settings["chunk_size"], 
                settings["overwrite_existing"]
            )
        
        return success, error_msg
    except Exception as e:
        return False, str(e)

def get_account_info(dbx):
    """Get information about the connected Dropbox account"""
    try:
        account_info = dbx.users_get_current_account()
        return {
            "name": f"{account_info.name.given_name} {account_info.name.surname}",
            "email": account_info.email,
            "country": account_info.country,
            "account_type": account_info.account_type,
            "profile_photo": account_info.profile_photo_url if hasattr(account_info, 'profile_photo_url') else None
        }
    except Exception as e:
        st.error(f"Error getting account info: {e}")
        return None

def get_space_usage(dbx):
    """Get space usage information for the Dropbox account"""
    try:
        space_usage = dbx.users_get_space_usage()
        used = space_usage.used
        allocated = space_usage.allocation.get_individual().allocated
        
        return {
            "used": used,
            "allocated": allocated,
            "used_formatted": format_size(used),
            "allocated_formatted": format_size(allocated),
            "percentage": (used / allocated) * 100 if allocated > 0 else 0
        }
    except Exception as e:
        st.error(f"Error getting space usage: {e}")
        return None

# Main app layout
st.markdown('<h1 class="main-header">📤 Advanced Dropbox Uploader</h1>', unsafe_allow_html=True)

# Sidebar for authentication and settings
with st.sidebar:
    st.image("https://www.dropbox.com/static/images/logo_catalog/dropbox_logo_glyph_2015_m1.svg", width=50)
    st.header("Authentication")
    
    # Authentication inputs
    app_key = st.text_input("App Key", type="password")
    app_secret = st.text_input("App Secret", type="password")
    refresh_token = st.text_input("Refresh Token", type="password")
    
    # Connect button
    if st.button("Connect to Dropbox"):
        if not app_key or not app_secret or not refresh_token:
            st.error("Please provide all Dropbox credentials.")
        else:
            with st.spinner("Connecting to Dropbox..."):
                dbx = get_dropbox_client(app_key, app_secret, refresh_token)
                if dbx:
                    st.success("Connected to Dropbox successfully!")
    
    # Logout button (only show if authenticated)
    if st.session_state.authenticated:
        if st.button("Logout"):
            logout()
    
    # Settings section
    st.markdown('<h2 class="sub-header">Settings</h2>', unsafe_allow_html=True)
    
    with st.expander("Upload Settings", expanded=False):
        max_file_size_mb = st.number_input(
            "Maximum File Size (MB)", 
            min_value=1, 
            max_value=2000, 
            value=st.session_state.settings["max_file_size_mb"]
        )
        
        allowed_extensions = st.text_input(
            "Allowed File Extensions", 
            value=st.session_state.settings["allowed_extensions"],
            help="Enter extensions separated by commas (e.g., .jpg,.pdf,.docx) or * for all files"
        )
        
        create_folders_if_not_exist = st.checkbox(
            "Create folders if they don't exist", 
            value=st.session_state.settings["create_folders_if_not_exist"]
        )
        
        overwrite_existing = st.checkbox(
            "Overwrite existing files", 
            value=st.session_state.settings["overwrite_existing"]
        )
        
        save_credentials = st.checkbox(
            "Remember credentials (browser only)", 
            value=st.session_state.settings["save_credentials"]
        )
        
        if st.button("Save Settings"):
            save_settings()
    
    # Help section
    with st.expander("How to get Dropbox API credentials"):
        st.markdown("""
        ### Steps to get your Dropbox API credentials:
        
        1. Go to the [Dropbox Developer App Console](https://www.dropbox.com/developers/apps)
        2. Click "Create app"
        3. Choose "Scoped access" API
        4. Choose "Full Dropbox" access type
        5. Name your app and click "Create app"
        6. In the app settings page:
           - Note your App key and App secret
           - Under "OAuth 2", add "http://localhost" to the redirect URIs
           - Under "Permissions", ensure you have the following permissions:
             - files.metadata.read
             - files.metadata.write
             - files.content.read
             - files.content.write
           - Click "Generate" under "Generated access token" section to get your refresh token
        
        These credentials are stored only in your browser session and are not saved by this application unless you check "Remember credentials".
        """)

# Main content area
if st.session_state.authenticated and st.session_state.dbx_client:
    # Display authentication status
    st.markdown('<div class="auth-status auth-connected">✅ Connected to Dropbox</div>', unsafe_allow_html=True)
    
    # Get account info and space usage
    account_info = get_account_info(st.session_state.dbx_client)
    space_usage = get_space_usage(st.session_state.dbx_client)
    
    # Display account info and space usage
    if account_info and space_usage:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<h3 class="sub-header">Account Information</h3>', unsafe_allow_html=True)
            st.markdown(f"""
            - **Name:** {account_info['name']}
            - **Email:** {account_info['email']}
            - **Country:** {account_info['country']}
            - **Account Type:** {account_info['account_type']}
            """)
        
        with col2:
            st.markdown('<h3 class="sub-header">Storage Usage</h3>', unsafe_allow_html=True)
            st.markdown(f"""
            - **Used:** {space_usage['used_formatted']}
            - **Total:** {space_usage['allocated_formatted']}
            """)
            
            # Progress bar for storage usage
            st.progress(space_usage['percentage'] / 100)
            st.caption(f"{space_usage['percentage']:.1f}% used")
    
    # File browser and uploader
    st.markdown('<h2 class="sub-header">File Browser & Uploader</h2>', unsafe_allow_html=True)
    
    # Current path and navigation
    col1, col2 = st.columns([3, 1])
    
    with col1:
        current_path = st.text_input("Current Path", value=st.session_state.current_folder)
        if current_path != st.session_state.current_folder:
            st.session_state.current_folder = normalize_path(current_path)
    
    with col2:
        if st.button("Go to Parent Folder"):
            parent_path = os.path.dirname(st.session_state.current_folder)
            st.session_state.current_folder = normalize_path(parent_path)
            st.experimental_rerun()
    
    # Create new folder
    with st.expander("Create New Folder", expanded=False):
        new_folder_name = st.text_input("Folder Name")
        if st.button("Create Folder") and new_folder_name:
            new_folder_path = os.path.join(st.session_state.current_folder, new_folder_name)
            new_folder_path = normalize_path(new_folder_path)
            
            if create_folder(st.session_state.dbx_client, new_folder_path):
                st.success(f"Folder created: {new_folder_path}")
                time.sleep(1)
                st.experimental_rerun()
    
    # List folder contents
    st.markdown('<h3 class="sub-header">Folder Contents</h3>', unsafe_allow_html=True)
    
    with st.spinner("Loading folder contents..."):
        folder_contents = list_folder(st.session_state.dbx_client, st.session_state.current_folder)
        
        # Separate folders and files
        folders = [item for item in folder_contents if isinstance(item, dropbox.files.FolderMetadata)]
        files = [item for item in folder_contents if isinstance(item, dropbox.files.FileMetadata)]
        
        # Sort alphabetically
        folders.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())
        
        # Display folders
        if folders:
            st.markdown("### 📁 Folders")
            for folder in folders:
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(f'<div class="folder-item">📁 {folder.name}</div>', unsafe_allow_html=True)
                with col2:
                    if st.button("Open", key=f"open_{folder.id}"):
                        st.session_state.current_folder = folder.path_display
                        st.experimental_rerun()
        
        # Display files
        if files:
            st.markdown("### 📄 Files")
            for file in files:
                col1, col2, col3 = st.columns([4, 1, 1])
                with col1:
                    icon = get_file_icon(file.name)
                    st.markdown(f'<div class="folder-item">{icon} {file.name} ({format_size(file.size)})</div>', unsafe_allow_html=True)
                with col2:
                    st.caption(f"Modified: {file.server_modified.strftime('%Y-%m-%d')}")
                with col3:
                    if st.button("Download", key=f"download_{file.id}"):
                        try:
                            metadata, response = st.session_state.dbx_client.files_download(file.path_display)
                            st.download_button(
                                label="Save File",
                                data=response.content,
                                file_name=file.name,
                                mime=get_mime_type(file.name),
                                key=f"save_{file.id}"
                            )
                        except Exception as e:
                            st.error(f"Error downloading file: {e}")
        
        # Empty folder message
        if not folders and not files:
            st.info("This folder is empty.")
    
    # File uploader
    st.markdown('<h2 class="sub-header">Upload Files</h2>', unsafe_allow_html=True)
    
    # Target folder selection
    target_folder = st.text_input(
        "Target Folder Path", 
        value=st.session_state.current_folder,
        help="The folder in your Dropbox where files will be uploaded"
    )
    
    # File uploader
    uploaded_files = st.file_uploader(
        "Choose files to upload", 
        accept_multiple_files=True
    )
    
    if uploaded_files:
        # File preview section
        st.markdown('<h3 class="sub-header">File Preview</h3>', unsafe_allow_html=True)
        
        # Display file information and previews
        for i, file in enumerate(uploaded_files):
            with st.expander(f"{get_file_icon(file.name)} {file.name} ({format_size(file.getbuffer().nbytes)})", expanded=i==0):
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.markdown(f"""
                    **File Details:**
                    - Size: {format_size(file.getbuffer().nbytes)}
                    - Type: {get_mime_type(file.name)}
                    """)
                    
                    # Validation warnings
                    if not is_valid_file_type(file.name):
                        st.warning(f"File type not allowed: {os.path.splitext(file.name)[1]}")
                    
                    if not is_valid_file_size(file.getbuffer().nbytes):
                        st.warning(f"File exceeds maximum size limit of {st.session_state.settings['max_file_size_mb']} MB")
                
                with col2:
                    if can_preview(file.name):
                        st.markdown('<div class="file-preview">', unsafe_allow_html=True)
                        st.markdown(generate_file_preview(file), unsafe_allow_html=True)
                        st.markdown('</div>', unsafe_allow_html=True)
                    else:
                        st.info("No preview available for this file type.")
        
        # Upload button
        if st.button("Upload to Dropbox"):
            if not target_folder:
                st.error("Please specify a target folder.")
            else:
                # Normalize target folder path
                target_folder = normalize_path(target_folder)
                
                # Create progress bar and status text
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Process each file
                successful_uploads = 0
                failed_uploads = 0
                total_files = len(uploaded_files)
                
                for i, file in enumerate(uploaded_files):
                    file_name = file.name
                    file_size = file.getbuffer().nbytes
                    
                    # Construct target path
                    target_path = os.path.join(target_folder, file_name).replace("\\", "/")
                    if not target_path.startswith("/"):
                        target_path = "/" + target_path
                    
                    # Update status
                    status_text.text(f"Uploading {i+1}/{total_files}: {file_name}...")
                    
                    # Validate file
                    if not is_valid_file_type(file_name):
                        add_to_upload_history(
                            file_name, 
                            file_size, 
                            target_path, 
                            "Failed", 
                            "File type not allowed"
                        )
                        failed_uploads += 1
                        continue
                    
                    if not is_valid_file_size(file_size):
                        add_to_upload_history(
                            file_name, 
                            file_size, 
                            target_path, 
                            "Failed", 
                            f"File exceeds maximum size limit of {st.session_state.settings['max_file_size_mb']} MB"
                        )
                        failed_uploads += 1
                        continue
                    
                    # Upload file
                    success, error_msg = upload_to_dropbox(
                        st.session_state.dbx_client, 
                        file, 
                        target_path, 
                        st.session_state.settings
                    )
                    
                    # Update history
                    if success:
                        add_to_upload_history(
                            file_name, 
                            file_size, 
                            target_path, 
                            "Success"
                        )
                        successful_uploads += 1
                    else:
                        add_to_upload_history(
                            file_name, 
                            file_size, 
                            target_path, 
                            "Failed", 
                            error_msg
                        )
                        failed_uploads += 1
                    
                    # Update progress
                    progress_bar.progress((i + 1) / total_files)
                
                # Show final status
                if successful_uploads == total_files:
                    st.success(f"Successfully uploaded all {successful_uploads} files to Dropbox!")
                elif successful_uploads > 0:
                    st.warning(f"Uploaded {successful_uploads} out of {total_files} files. {failed_uploads} files failed.")
                else:
                    st.error(f"Failed to upload any files. Please check the errors and try again.")
                
                # Refresh the folder contents
                time.sleep(1)
                st.experimental_rerun()
    
    # Upload history
    st.markdown('<h2 class="sub-header">Upload History</h2>', unsafe_allow_html=True)
    
    if st.session_state.upload_history:
        # Clear history button
        if st.button("Clear History"):
            clear_upload_history()
            st.experimental_rerun()
        
        # Display history
        for entry in st.session_state.upload_history:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            
            with col1:
                st.markdown(f"**{entry['file_name']}** ({entry['file_size']})")
            
            with col2:
                st.caption(f"Path: {entry['target_path']}")
            
            with col3:
                st.caption(f"Time: {entry['timestamp']}")
            
            with col4:
                if entry['status'] == "Success":
                    st.markdown("✅")
                else:
                    st.markdown("❌")
                    if st.button("Details", key=f"details_{entry['id']}"):
                        st.error(entry['error_message'])
    else:
        st.info("No upload history yet.")

else:
    # Not authenticated
    st.markdown('<div class="auth-status auth-disconnected">❌ Not connected to Dropbox</div>', unsafe_allow_html=True)
    
    # Welcome message and instructions
    st.markdown("""
    <div class="info-box">
        <h3>Welcome to Advanced Dropbox Uploader!</h3>
        <p>This application allows you to:</p>
        <ul>
            <li>Browse your Dropbox files and folders</li>
            <li>Upload files to Dropbox with progress tracking</li>
            <li>Create new folders in your Dropbox</li>
            <li>Preview files before uploading</li>
            <li>Track upload history</li>
            <li>Customize upload settings</li>
        </ul>
        <p>To get started, please enter your Dropbox API credentials in the sidebar and click "Connect to Dropbox".</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Features showcase
    st.markdown('<h2 class="sub-header">Key Features</h2>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        ### 📂 File Management
        - Browse files and folders
        - Create new folders
        - Download files
        - Upload multiple files
        """)
    
    with col2:
        st.markdown("""
        ### 🔍 File Preview
        - Preview images
        - Preview text files
        - Preview CSV data
        - File type detection
        """)
    
    with col3:
        st.markdown("""
        ### ⚙️ Advanced Settings
        - File type filtering
        - Size limits
        - Folder creation
        - Overwrite options
        """)
    
    # Demo image
    st.image("https://www.dropbox.com/static/images/logo_catalog/dropbox_logo_glyph_2015_m1.svg", width=100)

# Footer
st.markdown("""
<div class="footer">
    <p>Advanced Dropbox Uploader | Created with Streamlit</p>
    <p>Version 2.0.0 | Last Updated: May 2023</p>
</div>
""", unsafe_allow_html=True)

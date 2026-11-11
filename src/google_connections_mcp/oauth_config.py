"""
OAuth Configuration for Google Connections MCP Server
Centralized scope management for all Google services
"""

# All scopes we need for full access
ALL_SCOPES = [
    # Calendar - Read/Write
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/calendar.readonly',
    
    # Gmail - Read/Write/Send
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.send',
    
    # Drive - Full access to files
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
    
    # Sheets - Read/Write (included in Drive scope but explicit is clearer)
    'https://www.googleapis.com/auth/spreadsheets',
    
    # Docs - Read/Write (included in Drive but explicit)
    'https://www.googleapis.com/auth/documents',
    
    # Tasks - Read/Write
    'https://www.googleapis.com/auth/tasks',

    # Search Console - Read only (search performance, URL inspection, sitemaps)
    'https://www.googleapis.com/auth/webmasters.readonly',

    # Google Analytics (GA4) - Read only (reports, realtime, property list)
    'https://www.googleapis.com/auth/analytics.readonly'
]

# Scope descriptions for user consent screen
SCOPE_DESCRIPTIONS = {
    'calendar': 'Access and modify your calendar events',
    'gmail': 'Read, send, and manage your email',
    'drive': 'Access and manage your Google Drive files',
    'sheets': 'Read and write to Google Sheets',
    'docs': 'Access and edit Google Docs',
    'tasks': 'Access and manage Google Tasks',
    'search_console': 'View Search Console data for your sites',
    'analytics': 'View your Google Analytics data'
}

def get_required_scopes():
    """Returns all required scopes for the application"""
    return ALL_SCOPES

def get_service_scopes(service_name):
    """Get scopes for a specific service"""
    scope_map = {
        'calendar': [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/calendar.events'
        ],
        'gmail': [
            'https://www.googleapis.com/auth/gmail.modify',
            'https://www.googleapis.com/auth/gmail.compose',
            'https://www.googleapis.com/auth/gmail.send'
        ],
        'drive': [
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/drive.file'
        ],
        'sheets': [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ],
        'docs': [
            'https://www.googleapis.com/auth/documents',
            'https://www.googleapis.com/auth/drive'
        ],
        'tasks': [
            'https://www.googleapis.com/auth/tasks'
        ],
        'search_console': [
            'https://www.googleapis.com/auth/webmasters.readonly'
        ],
        'analytics': [
            'https://www.googleapis.com/auth/analytics.readonly'
        ]
    }
    return scope_map.get(service_name, [])

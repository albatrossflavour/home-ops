#!/usr/bin/env python3
"""
Paperless-NGX Initial Setup Script

This script uses the Paperless API to create:
- Tags (Person/Pet/Vehicle, Topic/Category, Business Context, Tax)
- Document Types
- Custom Fields
- Workflows (inbox auto-tagging)

Usage:
    export PAPERLESS_URL="https://paperless.albatrossflavour.com"
    export PAPERLESS_TOKEN="your-api-token-here"
    python3 paperless-setup.py
"""

import os
import sys
from typing import Dict

import requests

# Configuration
PAPERLESS_URL = os.getenv("PAPERLESS_URL", "https://paperless.albatrossflavour.com")
PAPERLESS_TOKEN = os.getenv("PAPERLESS_TOKEN")

if not PAPERLESS_TOKEN:
    print("ERROR: PAPERLESS_TOKEN environment variable not set")
    print("Get your token from: Paperless → Settings → API Tokens")
    sys.exit(1)

# API Headers
HEADERS = {
    "Authorization": f"Token {PAPERLESS_TOKEN}",
    "Content-Type": "application/json",
}

# Color palette for tags (you can customize)
COLORS = {
    "person": "#3498db",  # Blue for people
    "pet": "#e74c3c",  # Red for pets
    "vehicle": "#9b59b6",  # Purple for vehicles
    "medical": "#e67e22",  # Orange for medical
    "financial": "#27ae60",  # Green for financial
    "ndis": "#f39c12",  # Yellow for NDIS
    "personal": "#1abc9c",  # Teal for personal
    "pets": "#e74c3c",  # Red for pet category
    "property": "#34495e",  # Dark gray for property
    "vehicles": "#9b59b6",  # Purple for vehicle category
    "work": "#2c3e50",  # Darker gray for work
    "business": "#16a085",  # Dark teal for business
    "tax": "#c0392b",  # Dark red for tax
    "default": "#95a5a6",  # Light gray default
}


def api_get(endpoint: str) -> Dict:
    """Make GET request to Paperless API"""
    url = f"{PAPERLESS_URL}/api/{endpoint}/"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def api_post(endpoint: str, data: Dict) -> Dict:
    """Make POST request to Paperless API"""
    url = f"{PAPERLESS_URL}/api/{endpoint}/"
    response = requests.post(url, headers=HEADERS, json=data)
    response.raise_for_status()
    return response.json()


def get_color(tag_name: str) -> str:
    """Determine color based on tag name"""
    name_lower = tag_name.lower()

    # Check for category prefixes
    for key, color in COLORS.items():
        if name_lower.startswith(key):
            return color

    # Check for specific tags
    if name_lower in ["tony", "dani", "edward", "harri"]:
        return COLORS["person"]
    if name_lower in ["murphy", "jeff"]:
        return COLORS["pet"]
    if name_lower in ["mini", "trax", "laser", "imprezza"]:
        return COLORS["vehicle"]
    if name_lower in ["home", "smsf/dha", "toodle pip designs"]:
        return COLORS["business"]

    return COLORS["default"]


def create_tags():
    """Create all tags in the taxonomy with proper parent-child relationships"""
    print("\n=== Creating Tags ===")

    # Get existing tags
    existing_tags_response = api_get("tags")
    existing_tags_map = {
        tag["name"]: tag for tag in existing_tags_response.get("results", [])
    }

    created_count = 0
    skipped_count = 0

    def create_tag(name, parent_id=None):
        """Helper to create a single tag"""
        nonlocal created_count, skipped_count

        if name in existing_tags_map:
            print(f"  ⏭️  Skipping '{name}' (already exists)")
            skipped_count += 1
            return existing_tags_map[name]["id"]

        tag_data = {
            "name": name,
            "color": get_color(name),
            "is_inbox_tag": (name == "inbox"),
        }
        if parent_id:
            tag_data["parent"] = parent_id

        try:
            result = api_post("tags", tag_data)
            tag_id = result["id"]
            existing_tags_map[name] = result  # Cache for later lookups
            indent = "    " if parent_id else "  "
            print(f"{indent}✅ Created tag: {name}")
            created_count += 1
            return tag_id
        except requests.exceptions.HTTPError as e:
            print(f"  ❌ Failed to create '{name}': {e}")
            return None

    # Flat tags (no hierarchy)
    flat_tags = [
        "Tony",
        "Dani",
        "Edward",
        "Harri",
        "Home",
        "SMSF/DHA",
        "Toodle Pip Designs",
        "inbox",
    ]

    for tag_name in flat_tags:
        create_tag(tag_name)

    # Hierarchical tags (parent -> children)
    hierarchical_tags = {
        "Medical": [
            "Reports",
            "Discharge",
            "Prescriptions",
            "Appointments",
            "Test Results",
        ],
        "Financial": ["Bills", "Receipts", "Statements", "Invoices"],
        "NDIS": ["Plans", "Reports", "Invoices", "Correspondence"],
        "Personal": ["Certificates", "Legal", "Education", "Life Insurance"],
        "Pets": [
            "Murphy",
            "Jeff",
            "Veterinary",
            "Pet Registration",
            "Pet Insurance",
            "Boarding",
            "Records",
        ],
        "Property": [
            "Lease",
            "Home Insurance",
            "Property Manuals",
            "Utilities",
            "Property Repairs",
            "Renovations",
            "Rates",
            "Management",
        ],
        "Vehicles": [
            "Mini",
            "Trax",
            "Laser",
            "Imprezza",
            "Auto Insurance",
            "Vehicle Registration",
            "Service",
            "Vehicle Repairs",
            "Purchase",
            "Vehicle Manuals",
        ],
        "Work": ["CAC", "Orchard", "Puppet"],
    }

    # Create parent tags first, then children
    for parent_name, children in hierarchical_tags.items():
        parent_id = create_tag(parent_name)
        if parent_id:
            for child_name in children:
                create_tag(child_name, parent_id)

    # Tax hierarchical tags (Tax -> FY years)
    # Note: Person tags (Tony, Dani) are applied separately as flat tags
    tax_parent_id = create_tag("Tax")
    if tax_parent_id:
        for fy in ["FY2024-25", "FY2023-24", "FY2025-26"]:
            create_tag(fy, tax_parent_id)

    print(f"\nTags Summary: {created_count} created, {skipped_count} skipped")


def create_document_types():
    """Create all document types"""
    print("\n=== Creating Document Types ===")

    # Get existing document types
    existing_types = api_get("document_types")
    existing_type_names = {dt["name"] for dt in existing_types.get("results", [])}

    document_types = [
        "Invoice",
        "Receipt",
        "Bill",
        "Certificate",
        "Medical Report",
        "Medical Discharge",
        "NDIS Plan",
        "NDIS Report",
        "Bank Statement",
        "Legal Document",
        "Insurance Policy",
        "Tax Document",
    ]

    created_count = 0
    skipped_count = 0

    for doc_type_name in document_types:
        if doc_type_name in existing_type_names:
            print(f"  ⏭️  Skipping '{doc_type_name}' (already exists)")
            skipped_count += 1
            continue

        try:
            doc_type_data = {"name": doc_type_name}
            api_post("document_types", doc_type_data)
            print(f"  ✅ Created document type: {doc_type_name}")
            created_count += 1
        except requests.exceptions.HTTPError as e:
            print(f"  ❌ Failed to create '{doc_type_name}': {e}")

    print(f"\nDocument Types Summary: {created_count} created, {skipped_count} skipped")


def create_custom_fields():
    """Create custom fields"""
    print("\n=== Creating Custom Fields ===")

    # Get existing custom fields
    existing_fields = api_get("custom_fields")
    existing_field_names = {cf["name"] for cf in existing_fields.get("results", [])}

    custom_fields = [
        {"name": "Financial Year", "data_type": "string"},
        {"name": "Original Filename", "data_type": "string"},
        {"name": "Amount", "data_type": "monetary"},
        {"name": "Due Date", "data_type": "date"},
    ]

    created_count = 0
    skipped_count = 0

    for field in custom_fields:
        if field["name"] in existing_field_names:
            print(f"  ⏭️  Skipping '{field['name']}' (already exists)")
            skipped_count += 1
            continue

        try:
            api_post("custom_fields", field)
            print(f"  ✅ Created custom field: {field['name']} ({field['data_type']})")
            created_count += 1
        except requests.exceptions.HTTPError as e:
            print(f"  ❌ Failed to create '{field['name']}': {e}")

    print(f"\nCustom Fields Summary: {created_count} created, {skipped_count} skipped")


def create_inbox_workflow():
    """Create workflow to auto-apply inbox tag on document consumption"""
    print("\n=== Creating Inbox Workflow ===")

    # First, get the inbox tag ID
    tags = api_get("tags")
    inbox_tag = next(
        (tag for tag in tags.get("results", []) if tag["name"] == "inbox"), None
    )

    if not inbox_tag:
        print("  ⚠️  'inbox' tag not found. Create tags first.")
        return

    inbox_tag_id = inbox_tag["id"]

    # Check if workflow already exists
    existing_workflows = api_get("workflows")
    workflow_exists = any(
        wf.get("name") == "Auto-add inbox tag"
        for wf in existing_workflows.get("results", [])
    )

    if workflow_exists:
        print("  ⏭️  Skipping 'Auto-add inbox tag' workflow (already exists)")
        return

    # Create workflow
    workflow_data = {
        "name": "Auto-add inbox tag",
        "order": 0,
        "enabled": True,
        "triggers": [
            {
                "type": "consumption",
                "sources": [],  # Apply to all sources
                "filter_filename": None,
                "filter_path": None,
                "filter_mailrule": None,
            }
        ],
        "actions": [
            {
                "type": "assignment",
                "assign_tags": [inbox_tag_id],
                "assign_document_type": None,
                "assign_correspondent": None,
                "assign_storage_path": None,
                "assign_owner": None,
                "assign_view_users": [],
                "assign_view_groups": [],
                "assign_change_users": [],
                "assign_change_groups": [],
                "assign_custom_fields": [],
            }
        ],
    }

    try:
        api_post("workflows", workflow_data)
        print("  ✅ Created inbox workflow: Auto-add inbox tag on consumption")
    except requests.exceptions.HTTPError as e:
        print(f"  ❌ Failed to create inbox workflow: {e}")
        print(f"     Response: {e.response.text if hasattr(e, 'response') else 'N/A'}")


def main():
    """Main setup function"""
    print("=" * 60)
    print("Paperless-NGX Setup Script")
    print("=" * 60)
    print(f"Target URL: {PAPERLESS_URL}")

    try:
        # Test connection
        print("\n🔍 Testing API connection...")
        # Test with tags endpoint (simple and always exists)
        tags_response = api_get("tags")
        print(
            f"✅ Connected to Paperless (found {tags_response.get('count', 0)} existing tags)"
        )

        # Create all resources
        create_tags()
        create_document_types()
        create_custom_fields()
        create_inbox_workflow()

        print("\n" + "=" * 60)
        print("✅ Setup Complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Login to Paperless and verify tags/types/fields were created")
        print("2. Upload test documents to verify inbox workflow")
        print("3. Configure Paperless-AI auto-tagging settings")
        print("4. Start migration with small batch of documents")

    except requests.exceptions.HTTPError as e:
        print(f"\n❌ API Error: {e}")
        if hasattr(e, "response"):
            print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

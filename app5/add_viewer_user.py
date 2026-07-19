# add_viewer_user.py
import json
import uuid
from werkzeug.security import generate_password_hash
import os

USERS_FILE = 'users.json'


def create_viewer_user():
    """Create a viewer user that can see all projects but cannot edit"""

    # Check if users.json exists
    if not os.path.exists(USERS_FILE):
        print("❌ users.json not found! Please run the Flask app first.")
        return False

    # Read existing users
    try:
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
    except:
        print("❌ Error reading users.json")
        return False

    # Check if viewer already exists
    viewer_exists = False
    existing_viewer = None
    for user in users:
        if user.get('username') == 'viewer':
            viewer_exists = True
            existing_viewer = user
            break

    if viewer_exists:
        print("=" * 50)
        print("⚠️  Viewer user already exists!")
        print(f"   Username: {existing_viewer.get('username')}")
        print(f"   Role: {existing_viewer.get('role')}")
        print("=" * 50)
        return True

    # Create new viewer user
    new_viewer = {
        'id': str(uuid.uuid4()),
        'username': 'viewer',
        'password_hash': generate_password_hash('viewer123'),
        'email': 'viewer@example.com',
        'full_name': 'Viewer User',
        'role': 'viewer',
        'created_date': '2026-01-01T00:00:00',
        'last_login': None,
        'is_active': True
    }

    # Add to users list
    users.append(new_viewer)

    # Save the updated users file
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

    print("=" * 50)
    print("✅ VIEWER USER CREATED SUCCESSFULLY!")
    print("=" * 50)
    print(f"   Username: {new_viewer['username']}")
    print(f"   Password: viewer123")
    print(f"   Role: viewer")
    print("=" * 50)
    print("\n📋 Viewer capabilities:")
    print("   ✓ Can view ALL projects in the system")
    print("   ✓ Can download PDF reports")
    print("   ✗ Cannot create new projects")
    print("   ✗ Cannot edit existing projects")
    print("   ✗ Cannot delete projects")
    print("   ✗ Cannot access Admin Panel")
    print("=" * 50)

    return True


def create_admin_user():
    """Create an admin user if none exists"""

    if not os.path.exists(USERS_FILE):
        print("❌ users.json not found! Please run the Flask app first.")
        return False

    try:
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
    except:
        return False

    # Check if admin exists
    for user in users:
        if user.get('username') == 'admin':
            print("✓ Admin user already exists")
            return True

    # Create admin user
    admin_user = {
        'id': str(uuid.uuid4()),
        'username': 'admin',
        'password_hash': generate_password_hash('admin123'),
        'email': 'admin@example.com',
        'full_name': 'Administrator',
        'role': 'admin',
        'created_date': '2026-01-01T00:00:00',
        'last_login': None,
        'is_active': True
    }

    users.append(admin_user)

    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

    print("=" * 50)
    print("✅ ADMIN USER CREATED!")
    print(f"   Username: admin")
    print(f"   Password: admin123")
    print("=" * 50)

    return True


if __name__ == '__main__':
    print("\n🔧 User Creation Script")
    print("-" * 50)

    # Check if users.json exists
    if not os.path.exists(USERS_FILE):
        print("\n⚠️  users.json not found!")
        print("   Please run the Flask app first to create the database file.")
        print("\n   Steps:")
        print("   1. Run: python app.py")
        print("   2. Stop the server with Ctrl+C")
        print("   3. Run this script again")
        exit(1)

    # Create viewer user
    create_viewer_user()

    print("\n🎉 Done! You can now login with:")
    print("   👤 Username: viewer")
    print("   🔑 Password: viewer123")
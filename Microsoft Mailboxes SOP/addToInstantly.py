import sys
from main import bulkAddAccountToInstantly


# print(sys.argv)
if len(sys.argv) < 4:
    # print("Please enter file path that contains account credential to add")
    print("Usage: python3 addToInstantly.py <Instantly Email> <Instantly Password> <email_file_path> <password_file_path>")
    sys.exit(1)
email_file_path = sys.argv[3]
password_file_path = sys.argv[4]

orgName = ""
if len(sys.argv) == 6:
    orgName = sys.argv[5]

emails = open(email_file_path, "r").readlines()
emails = [email.strip() for email in emails]
passwords = open(password_file_path, "r").readlines()
passwords = [password.strip() for password in passwords]

if len(emails) > len(passwords):
    print("Emails and passwords count mismatch")
    sys.exit(1)

credentials = []
for email, password in zip(emails, passwords):
    credentials.append({
        "email": email,
        "password": password
    })

if len(credentials) == 0:
    print("No emails found in the file")
    sys.exit(1)


thread = bulkAddAccountToInstantly({
    "email": sys.argv[1],
    "password": sys.argv[2]
}, credentials, orgName)
thread.join()
print("All accounts added to Instantly")

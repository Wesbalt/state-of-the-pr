import smtplib, ssl, email

'''
Generate and send automated emails based on a template.
'''

# Email server and user
server_name     = "server.name"
server_port     = 0
client_username = "username"
client_password = input("Password to email user: ")

# Email contents
sender  = "Firstname Lastname <email@address.com>"
subject = "Subject"
body_template = """Hi <name> on the <repo> repository,

this is an unfinished email template. Thanks for reading."""

# Path to the file containing the users.
# Each line in the file must follow this format:
#  USERNAME,REAL_NAME,EMAIL,REPOSITORY
input_file_path = "users.txt"

# Read the user file
users = []
f = open(input_file_path, "r", encoding="utf8")
for line in f.read().splitlines():  users.append(line.split(","))
f.close()
print(f"Read {len(users)} users")

# Log in
server = smtplib.SMTP(server_name, port=server_port)
# server.set_debuglevel(1)
server.starttls(context=ssl.create_default_context())
server.login(client_username, client_password)
print("Logged in as " + client_username)

# Email the users
for i, user in enumerate(users):

	# Generate the email's body text
    username, user_real_name, user_email, user_repo = user
    name = user_real_name if user_real_name else username
    body = body_template.replace("<name>", name).replace("<repo>", user_repo)

    # Create the email
    message = email.message.EmailMessage()
    message.clear()
    message["from"]    = sender
    message["to"]      = user_email
    message["subject"] = subject
    message.set_content(body)

    # Send the email
    try:
        server.sendmail(sender, user_email, message.as_string())
        print(f"Emailed {user_email}")
    except Exception as e: # Likely a malformed email address
        print("Exception: " + repr(e))

    print(f"Progress: {(i+1) / len(users) :.1%} (line {i+1})")

server.quit()
print(f"Sent {len(users)} email(s)")
print("Done.")

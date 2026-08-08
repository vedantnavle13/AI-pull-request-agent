from app.agents.reviewer import review_code


diff = """
+password = input("Password: ")
+query = "SELECT * FROM users WHERE password = '" + password + "'"
"""


result = review_code(diff)

print(result)
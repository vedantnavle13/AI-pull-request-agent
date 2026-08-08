from app.agents.reviewer import review_code


diff = """
FILE: auth.py

@@ -10,3 +10,4 @@

+user_id = input("Enter user id: ")
+query = "SELECT * FROM users WHERE id = " + user_id
+cursor.execute(query)
"""


result = review_code(diff)

print("\n========== REVIEW ==========\n")

for finding in result.findings:

    print("Severity:", finding.severity)
    print("Category:", finding.category)
    print("File:", finding.file)
    print("Line:", finding.line)
    print("Title:", finding.title)
    print("Description:", finding.description)
    print("Suggestion:", finding.suggestion)
    print()
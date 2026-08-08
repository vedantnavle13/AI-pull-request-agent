def extract_diff(files):

    changes = []

    for file in files:

        changes.append({
            "filename": file["filename"],
            "status": file["status"],
            "additions": file["additions"],
            "deletions": file["deletions"],
            "patch": file.get("patch", ""),
        })

    return changes
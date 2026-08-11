class ReviewValidator:

    def __init__(self):
        self.errors: list[str] = []

    def validate(
        self,
        findings: list[dict],
        files: list[dict],
    ) -> list[dict]:
        """
        Validate AI-generated review findings.

        Checks:
        1. Required fields
        2. File existence
        3. Duplicate findings

        Invalid findings are removed and recorded in
        self.errors.
        """

        self.errors = []

        valid_files = {
            file.get("filename")
            for file in files
            if file.get("filename")
        }

        valid_findings = []
        seen = set()

        for index, finding in enumerate(findings):

            # ------------------------------------------------
            # 1. Required title
            # ------------------------------------------------

            if not finding.get("title"):
                self.errors.append(
                    f"Finding {index}: missing title"
                )
                continue

            # ------------------------------------------------
            # 2. Required description
            # ------------------------------------------------

            if not finding.get("description"):
                self.errors.append(
                    f"Finding {index}: missing description"
                )
                continue

            # ------------------------------------------------
            # 3. Required file
            # ------------------------------------------------

            if not finding.get("file"):
                self.errors.append(
                    f"Finding {index}: missing file"
                )
                continue

            # ------------------------------------------------
            # 4. Verify referenced file
            # ------------------------------------------------

            if (
                valid_files
                and finding["file"] not in valid_files
            ):
                self.errors.append(
                    f"Finding {index}: "
                    f"file '{finding['file']}' "
                    f"does not exist in the PR"
                )
                continue

            # ------------------------------------------------
            # 5. Remove duplicate findings
            # ------------------------------------------------

            key = (
                finding.get("file"),
                finding.get("line"),
                finding.get(
                    "title",
                    "",
                ).strip().lower(),
            )

            if key in seen:
                self.errors.append(
                    f"Finding {index}: duplicate finding"
                )
                continue

            seen.add(key)

            valid_findings.append(finding)

        return valid_findings
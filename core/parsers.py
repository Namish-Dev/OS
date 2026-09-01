def parse_vscode_title(window_title):
    """
    Extract basic information from a VS Code window title.
    """

    if not window_title:
        return {
            "file": None,
            "workspace": None
        }

    suffix = " - Visual Studio Code"

    if suffix not in window_title:
        return {
            "file": None,
            "workspace": None
        }

    content = window_title.replace(
        suffix,
        ""
    ).strip()

    parts = [
        part.strip()
        for part in content.split(" - ")
    ]

    if len(parts) >= 2:

        return {
            "file": parts[0],
            "workspace": parts[1]
        }

    return {
        "file": content,
        "workspace": None
    }


if __name__ == "__main__":

    examples = [
        "activity_tracker.py - OS - Visual Studio Code",
        "database.py - OS - Visual Studio Code",
        "main.py - MyProject - Visual Studio Code"
    ]

    for title in examples:

        result = parse_vscode_title(title)

        print(title)
        print(result)
        print()
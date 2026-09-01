"""
Personal OS — Activity Category Classifier.

Assigns a high-level category to a single (event + context) record.
This is the foundation Phase 2 builds on: sessionization, project
detection, and duration breakdowns all read the category a given
moment of activity belongs to.

Platform-independent — operates purely on already-extracted context
fields (application, domain, file, etc.), never on raw OS data.
"""

CODING = "Coding"
RESEARCH = "Research"
LEARNING = "Learning"
NOTES = "Notes"
COMMUNICATION = "Communication"
ENTERTAINMENT = "Entertainment"
FILES = "Files"
OTHER = "Other"

# Domains classified as research/development resources.
RESEARCH_DOMAINS = {
    "github.com",
    "stackoverflow.com",
    "stackexchange.com",
    "docs.python.org",
    "developer.mozilla.org",
    "fastapi.tiangolo.com",
    "readthedocs.io",
    "pypi.org",
    "npmjs.com",
    "medium.com",
    "dev.to",
    "arxiv.org",
    "kaggle.com",
}

# Domains classified as learning resources (courses, tutorials, docs sites
# aimed at structured learning rather than ad-hoc lookup).
LEARNING_DOMAINS = {
    "youtube.com",
    "coursera.org",
    "udemy.com",
    "freecodecamp.org",
    "khanacademy.org",
    "w3schools.com",
    "geeksforgeeks.org",
}

# Domains classified as communication.
COMMUNICATION_DOMAINS = {
    "mail.google.com",
    "outlook.com",
    "outlook.office.com",
    "slack.com",
    "discord.com",
    "teams.microsoft.com",
    "web.whatsapp.com",
    "web.telegram.org",
}

# Domains classified as entertainment / distraction.
ENTERTAINMENT_DOMAINS = {
    "netflix.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "twitch.tv",
    "primevideo.com",
    "hotstar.com",
}



def classify_event(application: str | None, context: dict | None) -> str:
    """
    Return the category for a single event.

    Args:
        application: Human-readable application name, e.g.
                     "Google Chrome", "Visual Studio Code".
        context:     The event's context dict (domain, file, note, etc.)
    """

    context = context or {}
    application = (application or "").lower()

    if "visual studio code" in application:
        return CODING

    if "antigravity" in application:
        return CODING

    if "obsidian" in application:
        return NOTES

    if "file explorer" in application:
        return FILES

    domain = (context.get("domain") or "").lower()

    if domain:

        # YouTube is ambiguous (learning vs entertainment) — video-sharing
        # platform, checked before generic learning/entertainment sets.
        if domain in LEARNING_DOMAINS:
            return LEARNING

        if domain in RESEARCH_DOMAINS:
            return RESEARCH

        if domain in COMMUNICATION_DOMAINS:
            return COMMUNICATION

        if domain in ENTERTAINMENT_DOMAINS:
            return ENTERTAINMENT

    return OTHER
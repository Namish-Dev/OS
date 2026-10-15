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

    # Browser domains do not have an inherent genre. A user-confirmed topic
    # rule may classify them; otherwise retain Other/Unclassified downstream.
    from core.topic_matcher import TopicMatcher
    topic = TopicMatcher().match(context)
    if topic:
        return topic[1]

    return OTHER

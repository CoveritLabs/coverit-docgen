KEEP_ATTRS = {
    "aria-label",
    "title",
    "alt",
    "placeholder",
    "value",
    "href",
    "type",
    "role",
    "name",
    "id",
    "for",
    "onclick",
}
TEXT_INPUT_TYPES = {"text", "search", "email", "url", "tel", "password", "number"}
INTERACTIVE_TAGS = {"a", "button", "input", "textarea", "select"}
INTERACTIVE_ROLES = {
    "button",
    "link",
    "tab",
    "menuitem",
    "option",
    "switch",
    "checkbox",
    "radio",
}

# attributes to be used for extracting the element name from it
#! order matters
NAME_ATTRS = {"aria-label", "title", "alt", "placeholder", "value", "name"}

MAX_DEPTH = 5

DIRECTION_RANGES = (
    ("right", 337.5, 360),
    ("right", 0, 22.5),
    ("top-right", 22.5, 67.5),
    ("top", 67.5, 112.5),
    ("top-left", 112.5, 157.5),
    ("left", 157.5, 202.5),
    ("bottom-left", 202.5, 247.5),
    ("bottom", 247.5, 292.5),
    ("bottom-right", 292.5, 337.5),
)

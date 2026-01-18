"""
Custom Block Font for TUI with Outline Effect.
"""

# Outlined block font - each letter has a visible border/outline
# Using box-drawing and block characters for the outline effect
OUTLINED_FONT = {
    'P': [
        "╔═══╗",
        "║ ╔═╝",
        "║ ╚╗ ",
        "╚══╝ ",
    ],
    'O': [
        "╔═══╗",
        "║   ║",
        "║   ║",
        "╚═══╝",
    ],
    'I': [
        "╔═╗",
        "║ ║",
        "║ ║",
        "╚═╝",
    ],
    'S': [
        "╔═══╗",
        "║ ══╝",
        "╚══ ║",
        "╚═══╝",
    ],
    'E': [
        "╔════╗",
        "║ ═══╝",
        "║ ═══╗",
        "╚════╝",
    ],
    'L': [
        "╔═╗  ",
        "║ ║  ",
        "║ ╚═╗",
        "╚═══╝",
    ],
    'A': [
        "╔═══╗",
        "║   ║",
        "║ ══╣",
        "╚╝ ╚╝",
    ],
    'T': [
        "╔═══╗",
        "╚═╦═╝",
        "  ║  ",
        "  ╚╝ ",
    ],
    'R': [
        "╔═══╗",
        "║ ╔═╝",
        "║ ╚╗ ",
        "╚╝╚╝ ",
    ],
    ' ': [
        "  ",
        "  ",
        "  ",
        "  ",
    ],
}

# Bold block font - thicker characters with consistent width
BLOCK_FONT = {
    'P': [
        "██████╗ ",
        "██╔══██╗",
        "██████╔╝",
        "██╔═══╝ ",
        "██║     ",
        "╚═╝     ",
    ],
    'O': [
        " ██████╗ ",
        "██╔═══██╗",
        "██║   ██║",
        "██║   ██║",
        "╚██████╔╝",
        " ╚═════╝ ",
    ],
    'I': [
        "██╗",
        "██║",
        "██║",
        "██║",
        "██║",
        "╚═╝",
    ],
    'S': [
        "███████╗",
        "██╔════╝",
        "███████╗",
        "╚════██║",
        "███████║",
        "╚══════╝",
    ],
    'E': [
        "███████╗",
        "██╔════╝",
        "█████╗  ",
        "██╔══╝  ",
        "███████╗",
        "╚══════╝",
    ],
    ' ': [
        "   ",
        "   ",
        "   ",
        "   ",
        "   ",
        "   ",
    ],
}

# Number of lines in the bold font
BOLD_FONT_LINES = 6

# Simple block font (fallback for other letters)
SIMPLE_BLOCK_FONT = {
    'A': ["█▀▀█", "█▄▄█", "█  █"],
    'B': ["█▀▀█", "█▀▀▄", "█▄▄█"],
    'C': ["█▀▀█", "█   ", "█▄▄█"],
    'D': ["█▀▀▄", "█  █", "█▄▄▀"],
    'E': ["█▀▀▀", "█▀▀▀", "█▄▄▄"],
    'F': ["█▀▀▀", "█▀▀▀", "█   "],
    'G': ["█▀▀▀", "█ ▀█", "█▄▄█"],
    'H': ["█  █", "█▀▀█", "█  █"],
    'I': ["█", "█", "█"],
    'J': ["   █", "   █", "█▄▄█"],
    'K': ["█ ▄▀", "█▀▄ ", "█ ▀▄"],
    'L': ["█   ", "█   ", "█▄▄▄"],
    'M': ["█▀▀█", "█  █", "█  █"],
    'N': ["█▄ █", "█ ▀█", "█  █"],
    'O': ["█▀▀█", "█  █", "█▄▄█"],
    'P': ["█▀▀█", "█▀▀▀", "█   "],
    'Q': ["█▀▀█", "█  █", "█▄▄█"],
    'R': ["█▀▀█", "█▄▄▀", "█  █"],
    'S': ["█▀▀▀", "▀▀▀█", "▄▄▄█"],
    'T': ["▀█▀", " █ ", " █ "],
    'U': ["█  █", "█  █", "█▄▄█"],
    'V': ["█  █", " ▀▀ ", "    "],
    'W': ["█  █", "█▄▄█", "█  █"],
    'X': ["▀▄ ▄▀", "  █  ", "▄▀ ▀▄"],
    'Y': ["█  █", "▀▄▄▀", "   █"],
    'Z': ["▀▀▀█", "  █ ", "█▄▄▄"],
    ' ': ["  ", "  ", "  "],
    '[': ["█", "█", "█"],
    ']': ["█", "█", "█"],
    '-': ["   ", "▀▀▀", "   "],
    '.': ["   ", "   ", " █ "],
}


def get_block_text(text: str) -> str:
    """Convert text to block font multiline string."""
    text = text.upper()
    lines = ["", "", ""]
    
    for char in text:
        block_char = BLOCK_FONT.get(char, ["   ", "   ", "   "])
        for i in range(3):
            lines[i] += block_char[i] + " "
            
    return "\n".join(lines)


def get_outlined_block_text(text: str, fg_color: str = "#3be8ff") -> str:
    """
    Convert text to bold block font with color styling.
    """
    text = text.upper()
    num_lines = BOLD_FONT_LINES
    lines = [""] * num_lines
    
    for char in text:
        block_char = BLOCK_FONT.get(char, ["   "] * num_lines)
        for i in range(num_lines):
            lines[i] += block_char[i] + " "
    
    # Apply color to all block/box-drawing characters
    result_lines = []
    block_chars = "█▀▄▐▌╔╗╚╝║═"
    
    for line in lines:
        styled_line = ""
        for char in line:
            if char in block_chars:
                styled_line += f"[{fg_color}]{char}[/]"
            else:
                styled_line += char
        result_lines.append(styled_line)
    
    return "\n".join(result_lines)


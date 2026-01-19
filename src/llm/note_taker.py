"""
AI Meeting Note Taker - LLM Note Taking Agent

Generates meeting notes from transcripts using LLMs.
"""

import os
from openai import OpenAI
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class MeetingNotes:
    """Structured meeting notes."""

    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    raw_response: str = ""


class NoteTaker:
    """LLM-powered meeting note generator."""

    SYSTEM_PROMPT = """You are an expert meeting note taker. Your job is to analyze meeting transcripts and produce clear, actionable meeting notes.

Given a transcript, extract:
1. **Summary**: A brief 2-3 sentence overview of what was discussed
2. **Key Points**: Important topics and information shared (bullet points)
3. **Action Items**: Tasks that need to be done, with assignees if mentioned
4. **Decisions**: Any decisions that were made
5. **Open Questions**: Unresolved questions or topics needing follow-up

Format your response EXACTLY like this:
## Summary
[Your summary here]

## Key Points
- [Point 1]
- [Point 2]

## Action Items
- [ ] [Action 1]
- [ ] [Action 2]

## Decisions
- [Decision 1]

## Open Questions
- [Question 1]

If a section has no items, write "None" instead of leaving it empty.
Be concise but comprehensive. Focus on actionable information."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "deepseek-ai/DeepSeek-V3.2-TEE",
    ):
        """
        Initialize the note taker.

        Args:
            api_key: OpenAI API key. Uses OPENAI_API_KEY env var if not provided.
            base_url: Custom API base URL (for local LLMs like Ollama).
            model: Model name to use.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model

        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            kwargs = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url

            self._client = OpenAI(**kwargs)
        return self._client

    def generate_notes(
        self,
        transcript: str,
        context: Optional[str] = None,
    ) -> MeetingNotes:
        """
        Generate meeting notes from a transcript.

        Args:
            transcript: The meeting transcript text.
            context: Optional context about the meeting (topic, participants).

        Returns:
            MeetingNotes object with extracted information.
        """
        client = self._get_client()

        user_message = f"Please analyze this meeting transcript and generate notes:\n\n{transcript}"

        if context:
            user_message = f"Context: {context}\n\n{user_message}"

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        raw_response = response.choices[0].message.content or ""
        return self._parse_notes(raw_response)

    def generate_incremental_notes(
        self,
        new_transcript: str,
        existing_notes: MeetingNotes,
    ) -> MeetingNotes:
        """
        Update existing notes with new transcript content.

        Args:
            new_transcript: New transcript segment.
            existing_notes: Previously generated notes.

        Returns:
            Updated MeetingNotes.
        """
        client = self._get_client()

        existing_summary = f"""
Current notes:
- Summary: {existing_notes.summary}
- Key Points: {', '.join(existing_notes.key_points) or 'None'}
- Action Items: {', '.join(existing_notes.action_items) or 'None'}
- Decisions: {', '.join(existing_notes.decisions) or 'None'}
"""

        user_message = f"""Here are the current meeting notes:
{existing_summary}

New transcript segment to incorporate:
{new_transcript}

Please update the meeting notes to include any new information from this segment. Keep existing information and add new items."""

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        raw_response = response.choices[0].message.content or ""
        return self._parse_notes(raw_response)

    def _parse_notes(self, response: str) -> MeetingNotes:
        """Parse LLM response into structured MeetingNotes."""
        notes = MeetingNotes(raw_response=response)

        sections = {
            "summary": [],
            "key_points": [],
            "action_items": [],
            "decisions": [],
            "questions": [],
        }

        current_section = None
        lines = response.strip().split("\n")

        for line in lines:
            line_lower = line.lower().strip()

            # Detect section headers
            if "## summary" in line_lower or line_lower.startswith("summary"):
                current_section = "summary"
            elif "## key points" in line_lower or "key points" in line_lower:
                current_section = "key_points"
            elif "## action" in line_lower or "action item" in line_lower:
                current_section = "action_items"
            elif "## decision" in line_lower or "decision" in line_lower:
                current_section = "decisions"
            elif "## open question" in line_lower or "question" in line_lower:
                current_section = "questions"
            elif current_section and line.strip():
                # Clean up bullet points and checkboxes
                clean_line = line.strip()
                if clean_line.startswith("-"):
                    clean_line = clean_line[1:].strip()
                if clean_line.startswith("[ ]") or clean_line.startswith("[x]"):
                    clean_line = clean_line[3:].strip()

                if clean_line and clean_line.lower() != "none":
                    sections[current_section].append(clean_line)

        # Assign to notes object
        notes.summary = " ".join(sections["summary"])
        notes.key_points = sections["key_points"]
        notes.action_items = sections["action_items"]
        notes.decisions = sections["decisions"]
        notes.questions = sections["questions"]

        return notes


# Simple test
if __name__ == "__main__":
    sample_transcript = """
    John: Alright, let's start the meeting. Today we need to discuss the Q1 roadmap.
    Sarah: I think we should prioritize the mobile app launch. It's been delayed too long.
    John: Agreed. What's the timeline looking like?
    Mike: If we start next week, we can have a beta by end of February.
    Sarah: That works. Mike, can you prepare the sprint plan by Friday?
    Mike: Sure, I'll have it ready.
    John: Great. Any blockers?
    Mike: We need the API docs from the backend team.
    John: I'll follow up with them today. Let's reconvene next Tuesday.
    """

    note_taker = NoteTaker()
    notes = note_taker.generate_notes(sample_transcript)

    print("=== Meeting Notes ===")
    print(f"\nSummary: {notes.summary}")
    print(f"\nKey Points:")
    for point in notes.key_points:
        print(f"  - {point}")
    print(f"\nAction Items:")
    for item in notes.action_items:
        print(f"  - [ ] {item}")
    print(f"\nDecisions:")
    for decision in notes.decisions:
        print(f"  - {decision}")

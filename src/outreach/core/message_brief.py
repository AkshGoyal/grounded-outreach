"""User-supplied sender facts and message intent; never inferred from research."""

from typing import Literal

from pydantic import BaseModel, Field


class MessageBrief(BaseModel):
    message_prompt: str = Field(default="", max_length=12000)
    topic: str = Field(default="", max_length=300)
    introduction: str = Field(default="", max_length=3500)
    background: str = Field(default="", max_length=3500)
    desired_response: str = Field(default="", max_length=500)
    tone: Literal["professional", "friendly", "concise"] = "professional"
    sender_name: str = Field(default="", max_length=150)

    def missing(self):
        if self.message_prompt.strip():
            return []
        if not any(
            (
                self.topic,
                self.introduction,
                self.background,
                self.desired_response,
                self.sender_name,
            )
        ):
            return ["Email instructions"]
        return [
            label
            for value, label in (
                (self.topic, "Campaign topic"),
                (self.introduction, "Your introduction or offer"),
                (self.desired_response, "What you want the recipient to do"),
            )
            if not value.strip()
        ]

    def campaign_copy(self):
        if self.missing():
            return ""
        if self.message_prompt.strip():
            # This is the editor source, not a prewritten email or inherited template.
            return self.message_prompt.replace("\r\n", "\n").replace("\r", "\n")
        background = self.background or "Not supplied; do not invent qualifications."
        name = self.sender_name or "Not supplied; do not invent a name."
        return (
            f"Campaign topic: {self.topic}\n"
            f"My introduction / offer: {self.introduction}\n"
            f"Relevant background (only supplied facts): {background}\n"
            f"Desired response: {self.desired_response}\n"
            f"Writing tone: {self.tone}\n"
            f"Sender name supplied for drafting: {name}\n"
            "Use only supplied sender facts. Do not claim the recipient has a vacancy "
            "or is hiring unless the reviewed evidence establishes it."
        )

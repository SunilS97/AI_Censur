from sqlmodel import Session

from ai_censur.database.models import Audio


def save_audio_record(
    session: Session, uncensored_file_path: str, censored_file_path: str
) -> str:
    audio = Audio(
        uncensored_file_path=uncensored_file_path,
        censored_file_path=censored_file_path,
    )
    session.add(audio)
    session.commit()
    return str(audio.id)

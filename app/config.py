from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str
    whatsapp_verify_token: str = "wastewatch-verify"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

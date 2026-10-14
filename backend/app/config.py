
from pydantic_settings import BaseSettings
class Settings(BaseSettings):
    app_name:str="BLUECARBON ARENA"
    database_url:str="sqlite:///./bluecarbon.db"
    secret_key:str="dev-only-change-me-please-32chars-minimum"
    access_token_minutes:int=480
    cors_origins:str="http://localhost:5173,http://localhost:3000"
    upload_dir:str="./uploads"
    demo_mode:bool=True
    class Config: env_file=".env"
settings=Settings()

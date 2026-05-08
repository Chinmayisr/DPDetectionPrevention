from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    OPENAI_API_KEY: str

    REDIS_URL: str

    QDRANT_HOST: str
    QDRANT_PORT: int

    MCP_SERVER_HOST: str = "localhost"
    MCP_SERVER_PORT: int = 8001

    class Config:
        env_file = ".env"


settings = Settings()
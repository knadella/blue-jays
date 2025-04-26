from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
engine = create_engine(os.getenv('DB_URL'))

@app.get("/")
async def root():
    return {"message": "Blue Jays Statcast API"}

@app.get("/api/statcast")
async def get_statcast_data():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT * FROM statcast_data"))
        return [dict(row) for row in result]

@app.get("/api/statcast/{player_id}")
async def get_player_statcast(player_id: int):
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT * FROM statcast_data WHERE batter = :player_id"),
            {"player_id": player_id}
        )
        return [dict(row) for row in result]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
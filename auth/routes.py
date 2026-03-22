from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Optional
from pydantic import BaseModel
import jwt
import datetime

app = FastAPI()

# JWT Secret Key
SECRET_KEY = "your_secret_key"

# OAuth2 scheme for JWT
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Dummy user store for example; replace with actual users
fake_users_db = {
    "testuser": {
        "username": "testuser",
        "full_name": "Test User",
        "email": "testuser@example.com",
        "hashed_password": "fakehashedsecret",
        "disabled": False,
    }
}

# User model
class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

# Login form model
class LoginForm(BaseModel):
    username: str
    password: str

# Utility function to verify password
def fake_hash_password(password: str):
    return "fakehashed" + password

# Show login route
@app.get("/login")
async def show_login():
    return {"message": "Login page"}

# Perform login route
@app.post("/login")
async def do_login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = fake_users_db.get(form_data.username)
    if not user or not fake_hash_password(form_data.password) == user['hashed_password']:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    # Create JWT token
    token = jwt.encode({"sub": form_data.username, "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=30)}, SECRET_KEY, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer"}

# Dashboard route
@app.get("/dashboard")
async def dashboard(token: str = Depends(oauth2_scheme)):
    return {"message": "Welcome to the dashboard!"}

# Get current user info route
@app.get("/users/me", response_model=User)
async def get_user_me(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    user = fake_users_db.get(username)
    if user is None:
        raise credentials_exception
    return user

# Logout route
@app.post("/logout")
async def logout():
    return {"message": "Logged out successfully"}

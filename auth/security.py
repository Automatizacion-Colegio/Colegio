from datetime import datetime, timedelta
import os
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models.database import get_db, UserDB

# Configuración de JWT (El SECRET_KEY viene del .env ahora)
SECRET_KEY = os.getenv("JWT_SECRET", "default_secret_if_env_fails")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None
    role: str | None = None
    user_id: int | None = None

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or account suspended",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        user_id: int = payload.get("user_id")
        if username is None or role is None:
            raise credentials_exception
            
        # Validate against DB for suspensions
        user = db.query(UserDB).filter(UserDB.id == user_id).first()
        if not user or not user.is_active:
            raise credentials_exception
            
        token_data = TokenData(username=username, role=role, user_id=user_id)
    except JWTError:
        raise credentials_exception
    return token_data

async def get_current_user_optional(token: str = Depends(OAuth2PasswordBearer(tokenUrl="token", auto_error=False))):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        user_id: int = payload.get("user_id")
        if username is None:
            return None
        return TokenData(username=username, role=role, user_id=user_id)
    except JWTError:
        return None

def require_role(allowed_roles: list[str]):
    def role_checker(current_user: TokenData = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Operation not permitted")
        return current_user
    return role_checker

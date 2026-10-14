
import jwt
from datetime import datetime,timedelta,timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends,HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User
ph=PasswordHasher(); bearer=HTTPBearer(auto_error=False)
def hash_pw(p): return ph.hash(p)
def verify_pw(p,h):
    try: return ph.verify(h,p)
    except Exception: return False
def create_token(u:User):
    exp=datetime.now(timezone.utc)+timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub":str(u.id),"role":u.role,"exp":exp},settings.secret_key,algorithm="HS256")
def get_current_user(cred=Depends(bearer),db:Session=Depends(get_db)):
    if not cred: raise HTTPException(401,"Not authenticated")
    try: payload=jwt.decode(cred.credentials,settings.secret_key,algorithms=["HS256"])
    except Exception: raise HTTPException(401,"Invalid or expired token")
    u=db.get(User,int(payload["sub"]))
    if not u or not u.is_active: raise HTTPException(401,"User inactive")
    return u
def require(*roles):
    def dep(u:User=Depends(get_current_user)):
        if u.role not in roles and u.role!="admin": raise HTTPException(403,"Forbidden for your role")
        return u
    return dep

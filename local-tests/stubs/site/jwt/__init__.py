def decode(token,secret,algorithms=None):return {"sub":token}
def encode(payload,secret,algorithm=None):return str(payload.get("sub",""))

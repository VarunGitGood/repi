from datetime import datetime
from repi.intent.resolver import resolve, ClarificationNeeded

now = datetime(2026, 5, 4, 12, 0, 0) # Monday
known_services = ["cart-svc", "inventory-svc", "payment-svc"]

query = "why did it break? (User Clarification: Friday night around 10pm)"
res = resolve(query, known_services, now)

print(f"Query: {query}")
print(f"Result Type: {type(res)}")
if isinstance(res, ClarificationNeeded):
    print(f"Question: {res.question}")
    print(f"Missing Dims: {res.missing_dims}")
else:
    print(f"Time From: {res.time_from}")
    print(f"Time To: {res.time_to}")
    print(f"Services: {res.services}")
    print(f"Symptoms: {res.symptoms}")
    print(f"Assumed: {res.assumed}")

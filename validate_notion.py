import os
from notion_client import Client

notion = Client(auth=os.environ["NOTION_TOKEN"])

db_id = os.environ["NOTION_RESEARCH_DB_ID"]
print("Trying to retrieve database:", db_id)

db = notion.databases.retrieve(database_id=db_id)
title = "".join([t.get("plain_text","") for t in db.get("title", [])])
print("SUCCESS. Database title:", title if title else "(no title)")

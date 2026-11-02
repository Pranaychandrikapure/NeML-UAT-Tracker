import os;from dotenv import load_dotenv;load_dotenv('/app/backend/.env');from pymongo import MongoClient
d=MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
for c in d.list_collection_names():
    if c=='users': d.users.delete_many({'$or':[{'is_demo':True},{'is_test':True},{'email':{'$regex':'^TEST_|example.com$'}}]})
    elif c!='tech_options': d[c].delete_many({})

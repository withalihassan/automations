import os
# DB config
DB_HOST = os.getenv('DB_HOST', 'database-1.ct22ws4u0c7g.me-central-1.rds.amazonaws.com')
DB_NAME = os.getenv('DB_NAME', 'manage_shein')
DB_USER = os.getenv('DB_USER', 'admin')
DB_PASS = os.getenv('DB_PASS', 'sLoGMCVfEo4TpMGOEm18')
DB_PORT = int(os.getenv('DB_PORT', '3306'))

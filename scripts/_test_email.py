import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

LOG = open('_email_out.txt', 'w', encoding='utf-8')

def log(msg=''):
    print(msg)
    LOG.write(msg + '\n')
    LOG.flush()

from email_skill import run_email_standalone

log("[test] starting email skill...")
results = run_email_standalone(
    csv_path='data/geo-week-talks.csv',
    goal=(
        "thank the speaker for their presentation and introduce Upskilled Consulting's "
        "newly launched ML/AI eLearning platform as a resource for their team and broader community"
    ),
    output_dir='email_drafts/',
    producer_model='llama3.2:3b',
    sender_name='Nick McCarty',
    sender_email='nick@upskilled.consulting',
    sender_company='Upskilled Consulting',
    platform_url='upskilled.consulting/courses',
    max_emails=160,
)
log()
for r in results:
    log('---')
    log(f"To: {r['name']} | {r['to_email']}")
    log(f"Subject: {r['subject']}")
    log()
    log(r['body'])
    log()
log("[test] DONE")
LOG.close()

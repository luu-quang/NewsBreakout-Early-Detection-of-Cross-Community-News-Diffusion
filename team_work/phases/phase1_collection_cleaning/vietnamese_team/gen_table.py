import pandas as pd

df = pd.read_parquet('team_work/phases/phase1_collection_cleaning/vietnamese_team/sample_output/sample_vn_cleaned.parquet')

df_true = df[df['vietnam_relevance'] == True].sample(n=min(15, len(df[df['vietnam_relevance'] == True])), random_state=42)
df_false = df[df['vietnam_relevance'] == False].sample(n=min(15, len(df[df['vietnam_relevance'] == False])), random_state=42)

df_sample = pd.concat([df_true, df_false])

with open('sample_table.md', 'w', encoding='utf-8') as f:
    f.write('### Sample Classification Table\n')
    f.write('| article_id | publisher_id | category | title | vietnam_relevance |\n')
    f.write('|---|---|---|---|---|\n')
    for _, row in df_sample.iterrows():
        title = str(row['title']).replace('|', '&#124;').replace('\n', ' ')
        cat = str(row['category']).replace('|', '&#124;')
        f.write(f"| {row['article_id']} | {row['publisher_id']} | {cat} | {title} | {row['vietnam_relevance']} |\n")

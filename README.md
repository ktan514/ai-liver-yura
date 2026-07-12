

## PostgreSQL(Docker)起動コマンド

``` bash
docker run --name postgres-m4 \
  -e POSTGRES_USER=ai_liver \
  -e POSTGRES_PASSWORD=ai_liver_password \
  -e POSTGRES_DB=ai_liver \
  -p 5432:5432 \
  -v ai_liver_postgres_data:/var/lib/postgresql/data \
  -d pgvector/pgvector:pg16
```

## VoiceVox
`VoiceVox Engine`を起動して使用する。
```bash
cd VoiceVoxEngineのパス
./run
```


# ヒーロー一覧更新（2026-11-18）

- D.Mon（Tank）を追加
- Doctrine（Support）を追加
- SombraをDamageからSupportに変更（2026-10-06のロール変更）
- 合計54ヒーロー（Tank 15 / Damage 23 / Support 16）
- 未実装のHudsonは追加していません。

ヒーロー一覧は `ban_logic.py` の `HEROES_BY_ROLE` で管理され、`app.py` と `app_standalone.py` の両方に反映されます。BAN計算ルール（7/5/3点など）は変更していません。

参考:
- https://overwatch.blizzard.com/en-us/heroes/
- https://overwatch.blizzard.com/en-us/news/patch-notes/live/2026/10/
- https://overwatch.blizzard.com/en-us/news/patch-notes/live/2026/08/

テスト: `python -m unittest discover -s tests -v`

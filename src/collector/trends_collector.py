from __future__ import annotations

import time

from pytrends.request import TrendReq


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def get_search_volumes(skills: list[str]) -> dict[str, int]:
    """
    各スキルのGoogle Trends検索ボリューム年間平均を取得する。
    pytrendsを使用する。
    5件ずつまとめて取得してRate Limit対策としてsleep(1)を入れる。
    取得失敗したスキルは0として扱う。
    """
    try:
        print(f"[Trends] 検索ボリュームを取得中: {len(skills)}件")
        volumes = {skill: 0 for skill in skills}
        if not skills:
            return volumes

        pytrends = TrendReq(hl="ja-JP", tz=540)
        for chunk in _chunked(skills, 5):
            success = False
            for attempt in range(1, 4):
                try:
                    print(f"[Trends] 取得中: {chunk} (attempt {attempt}/3)")
                    pytrends.build_payload(chunk, timeframe="today 12-m", geo="JP")
                    data = pytrends.interest_over_time()
                    if data.empty:
                        print(f"[Trends][WARN] 空のレスポンス: {chunk}")
                    else:
                        for skill in chunk:
                            if skill in data:
                                volumes[skill] = int(round(float(data[skill].mean())))
                    success = True
                    break
                except Exception as exc:
                    print(f"[Trends][WARN] 取得失敗: {chunk} ({exc})")
                    if attempt < 3:
                        time.sleep(2)
            if not success:
                print(f"[Trends][WARN] 失敗したチャンクは0として扱います: {chunk}")
            time.sleep(1)
        return volumes
    except Exception as exc:
        print(f"[Trends][WARN] 検索ボリューム取得に失敗しました: {exc}")
        return {skill: 0 for skill in skills}

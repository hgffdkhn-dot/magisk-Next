#!/usr/bin/env python3
"""更新通道清单校验（magisk-Next update channel）。

定义 magisk-Next 更新清单格式，做结构校验、产物 SHA256 校验，以及基于
系统 openssl 的 RSA 签名/验签。纯标准库（签名能力依赖外部 openssl 命令，
缺失时如实报错，不降级为"假装验签成功"）。

清单格式：
    {
      "brand": "magisk-Next",
      "channel": "https://example.com/next.json",
      "version": "31.1-next.3",
      "versionCode": 1000001,
      "generated_at": "2026-11-07T08:30:00Z",
      "artifacts": [
        {"name": "app-release.apk", "url": "https://...", "sha256": "<64 hex>", "size": 123}
      ],
      "signature": {"algorithm": "sha256-rsa", "key_id": "next-2026", "value": "<base64>"}
    }

签名对象：剔除 signature 字段后，键排序、无多余空白的 UTF-8 JSON 字节。

用法：
    python3 next/channel.py template
    python3 next/channel.py verify --manifest F [--public-key PEM] [--artifact-dir D]
    python3 next/channel.py sign   --manifest F --private-key PEM [--key-id ID]
    python3 next/channel.py --self-test
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_common import (  # noqa: E402
    BRAND, FAIL, PASS, WARN, issue, sha256_file,
)

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
REQUIRED = ("brand", "channel", "version", "versionCode", "generated_at", "artifacts")


def canonical_bytes(data: dict) -> bytes:
    """返回用于签名的规范化字节（剔除 signature 字段）。"""
    body = {k: v for k, v in data.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def openssl_available() -> bool:
    return shutil.which("openssl") is not None


def _run_openssl(args: list[str], data: bytes) -> subprocess.CompletedProcess:
    return subprocess.run(["openssl", *args], input=data,
                          capture_output=True, timeout=30)


def validate(data: dict) -> list:
    """清单结构校验，返回问题列表（FAIL 级别即不可用）。"""
    problems: list = []
    if not isinstance(data, dict):
        return [issue(FAIL, "NOT_OBJECT", "清单根节点必须是 JSON 对象")]
    for k in REQUIRED:
        if k not in data:
            problems.append(issue(FAIL, "MISSING_FIELD", f"缺少字段 {k}"))
    if data.get("brand") and data["brand"] != BRAND:
        problems.append(issue(FAIL, "WRONG_BRAND",
                              f"brand 不是 {BRAND}: {data.get('brand')!r}"))
    ch = data.get("channel", "")
    if ch and not str(ch).startswith("https://"):
        problems.append(issue(FAIL, "INSECURE_CHANNEL", "channel 必须是 HTTPS URL"))
    vc = data.get("versionCode")
    if vc is not None and (not isinstance(vc, int) or isinstance(vc, bool) or vc < 0):
        problems.append(issue(FAIL, "BAD_VERSION_CODE", "versionCode 必须是非负整数"))
    arts = data.get("artifacts", [])
    if not isinstance(arts, list) or not arts:
        problems.append(issue(FAIL, "NO_ARTIFACTS", "artifacts 必须是非空数组"))
    else:
        seen = set()
        for i, a in enumerate(arts):
            if not isinstance(a, dict):
                problems.append(issue(FAIL, "BAD_ARTIFACT", f"artifacts[{i}] 不是对象"))
                continue
            for k in ("name", "url", "sha256"):
                if not a.get(k):
                    problems.append(issue(FAIL, "BAD_ARTIFACT",
                                          f"artifacts[{i}] 缺少 {k}"))
            name = str(a.get("name", ""))
            if name in seen:
                problems.append(issue(FAIL, "DUPLICATE_ARTIFACT", f"产物名重复: {name}"))
            seen.add(name)
            if name and (Path(name).is_absolute() or ".." in Path(name).parts):
                problems.append(issue(FAIL, "UNSAFE_NAME", f"产物名含路径穿越: {name}"))
            if a.get("url") and not str(a["url"]).startswith("https://"):
                problems.append(issue(FAIL, "INSECURE_URL",
                                      f"artifacts[{i}].url 必须是 HTTPS"))
            if a.get("sha256") and not SHA256_RE.match(str(a["sha256"])):
                problems.append(issue(FAIL, "BAD_SHA256",
                                      f"artifacts[{i}].sha256 不是 64 位十六进制"))
            if "size" in a and (not isinstance(a["size"], int) or a["size"] < 0):
                problems.append(issue(WARN, "BAD_SIZE", f"artifacts[{i}].size 应为非负整数"))
    sig = data.get("signature")
    if sig is not None:
        if not isinstance(sig, dict) or not sig.get("value"):
            problems.append(issue(FAIL, "BAD_SIGNATURE", "signature 格式不完整"))
        elif sig.get("algorithm") != "sha256-rsa":
            problems.append(issue(FAIL, "UNSUPPORTED_ALGORITHM",
                                  f"不支持的签名算法: {sig.get('algorithm')}"))
    return problems


def verify_artifacts(data: dict, directory: Path) -> list:
    """校验本地产物文件与清单里的 sha256 / size 一致。"""
    problems: list = []
    for a in data.get("artifacts", []):
        if not isinstance(a, dict) or not a.get("name"):
            continue
        f = directory / a["name"]
        if not f.is_file():
            problems.append(issue(FAIL, "ARTIFACT_MISSING", f"产物不存在: {a['name']}"))
        elif sha256_file(f).lower() != str(a.get("sha256", "")).lower():
            problems.append(issue(FAIL, "ARTIFACT_HASH_MISMATCH",
                                  f"产物校验和不匹配: {a['name']}",
                                  "请勿刷入校验失败的产物"))
        elif "size" in a and f.stat().st_size != a["size"]:
            problems.append(issue(WARN, "ARTIFACT_SIZE_MISMATCH",
                                  f"产物大小与清单不符: {a['name']}"))
    return problems


def sign(data: dict, private_key: Path, key_id: str = "default") -> dict:
    if not openssl_available():
        raise RuntimeError("未找到 openssl，无法签名")
    if not private_key.is_file():
        raise FileNotFoundError(f"私钥不存在: {private_key}")
    raw = canonical_bytes(data)
    r = _run_openssl(["dgst", "-sha256", "-sign", str(private_key)], raw)
    if r.returncode:
        raise RuntimeError("openssl 签名失败: " + r.stderr.decode(errors="replace").strip()[:200])
    data = dict(data)
    data["signature"] = {
        "algorithm": "sha256-rsa",
        "key_id": key_id,
        "value": base64.b64encode(r.stdout).decode("ascii"),
    }
    return data


def verify_signature(data: dict, public_key: Path) -> list:
    """返回问题列表；空列表表示验签通过。"""
    if not openssl_available():
        return [issue(FAIL, "NO_OPENSSL", "未找到 openssl，无法验签")]
    if not public_key.is_file():
        return [issue(FAIL, "NO_PUBLIC_KEY", f"公钥不存在: {public_key}")]
    sig = data.get("signature")
    if not isinstance(sig, dict) or not sig.get("value"):
        return [issue(FAIL, "NO_SIGNATURE", "清单未签名")]
    if sig.get("algorithm") != "sha256-rsa":
        return [issue(FAIL, "UNSUPPORTED_ALGORITHM",
                      f"不支持的签名算法: {sig.get('algorithm')}")]
    try:
        blob = base64.b64decode(sig["value"], validate=True)
    except (ValueError, binascii.Error) as e:
        return [issue(FAIL, "BAD_SIGNATURE", f"签名不是合法 base64: {e}")]
    with tempfile.NamedTemporaryFile(suffix=".sig", delete=False) as tmp:
        tmp.write(blob)
        sig_path = tmp.name
    try:
        r = _run_openssl(["dgst", "-sha256", "-verify", str(public_key),
                          "-signature", sig_path], canonical_bytes(data))
    finally:
        Path(sig_path).unlink(missing_ok=True)
    if r.returncode:
        return [issue(FAIL, "SIGNATURE_INVALID", "验签失败：清单可能被篡改或密钥不匹配",
                      "不要应用此更新，请从可信来源重新获取清单")]
    return []


def template() -> dict:
    return {
        "brand": BRAND,
        "channel": "https://example.com/magisk-next.json",
        "version": "31.1-next.3",
        "versionCode": 1000001,
        "generated_at": "2026-11-07T08:30:00Z",
        "artifacts": [
            {"name": "app-release.apk",
             "url": "https://example.com/app-release.apk",
             "sha256": "0" * 64, "size": 0},
        ],
    }


def self_test() -> int:
    d = template()
    assert not [i for i in validate(d) if i["level"] == FAIL], validate(d)
    bad = dict(d, channel="http://insecure.example/x.json",
               versionCode="not-int",
               artifacts=[{"name": "../evil.apk", "url": "http://x", "sha256": "xyz"}])
    codes = {i["code"] for i in validate(bad)}
    assert {"INSECURE_CHANNEL", "BAD_VERSION_CODE", "UNSAFE_NAME",
            "INSECURE_URL", "BAD_SHA256"} <= codes, codes

    # 结构 + 产物校验（不依赖 openssl）
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        apk = root / "app-release.apk"
        apk.write_bytes(b"signed-apk-bytes")
        d2 = dict(d, artifacts=[{"name": "app-release.apk",
                                 "url": "https://example.com/app-release.apk",
                                 "sha256": sha256_file(apk),
                                 "size": apk.stat().st_size}])
        assert not verify_artifacts(d2, root), verify_artifacts(d2, root)
        apk.write_bytes(b"TAMPERED")
        assert "ARTIFACT_HASH_MISMATCH" in {i["code"] for i in verify_artifacts(d2, root)}

        # 真实验签（openssl 存在时）
        if openssl_available():
            priv, pub = root / "priv.pem", root / "pub.pem"
            g = subprocess.run(["openssl", "genpkey", "-algorithm", "RSA",
                                "-pkeyopt", "rsa_keygen_bits:2048",
                                "-out", str(priv)], capture_output=True, timeout=60)
            assert g.returncode == 0, g.stderr.decode()[:200]
            p = subprocess.run(["openssl", "pkey", "-in", str(priv),
                                "-pubout", "-out", str(pub)],
                               capture_output=True, timeout=30)
            assert p.returncode == 0, p.stderr.decode()[:200]
            signed = sign(d2, priv, key_id="selftest")
            assert not [i for i in validate(signed) if i["level"] == FAIL], validate(signed)
            assert not verify_signature(signed, pub), verify_signature(signed, pub)
            tampered = dict(signed, versionCode=9999999)
            assert "SIGNATURE_INVALID" in {i["code"] for i in
                                           verify_signature(tampered, pub)}
            print("  (openssl RSA 签名/验签/篡改检测 已实测)")
        else:
            print("  (openssl 不可用，跳过验签实测；结构校验仍通过)")
    print("channel self-test: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{BRAND} 更新通道清单校验")
    ap.add_argument("action", nargs="?", choices=("template", "verify", "sign"))
    ap.add_argument("--manifest", type=Path, help="清单 JSON 路径")
    ap.add_argument("--public-key", type=Path, help="PEM 公钥（验签）")
    ap.add_argument("--private-key", type=Path, help="PEM 私钥（签名）")
    ap.add_argument("--key-id", default="default", help="签名 key_id")
    ap.add_argument("--artifact-dir", type=Path, help="本地产物目录，一并校验 sha256")
    ap.add_argument("--output", type=Path, help="sign 输出路径（默认覆盖 manifest）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    if args.action == "template":
        print(json.dumps(template(), ensure_ascii=False, indent=2))
        return 0
    if not args.action or not args.manifest:
        ap.error("请指定 template / verify / sign，verify/sign 需要 --manifest")
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[FAIL] 读取清单失败: {e}", file=sys.stderr)
        return 1

    if args.action == "sign":
        try:
            signed = sign(data, args.private_key or Path(""), args.key_id)
        except (RuntimeError, FileNotFoundError) as e:
            print(f"[FAIL] {e}", file=sys.stderr)
            return 1
        out = args.output or args.manifest
        out.write_text(json.dumps(signed, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"[ OK ] 已签名并写入 {out}（key_id={args.key_id}）")
        return 0

    # verify
    problems = validate(data)
    if args.artifact_dir:
        problems += verify_artifacts(data, args.artifact_dir)
    if args.public_key:
        problems += verify_signature(data, args.public_key)
    else:
        problems.append(issue(WARN, "UNVERIFIED", "未提供 --public-key，未做签名验证",
                              "生产环境务必提供公钥验签，仅做结构校验不足以防篡改"))
    if args.json:
        print(json.dumps({"problems": problems,
                          "ok": not any(i["level"] == FAIL for i in problems)},
                         ensure_ascii=False, indent=2))
    else:
        if not problems:
            print(f"[ OK ] 清单 {args.manifest} 校验通过")
        for i in problems:
            print(f"[{i['level']:4s}] {i['code']}: {i['message']}")
            if i["hint"]:
                print(f"        -> {i['hint']}")
    return 1 if any(i["level"] == FAIL for i in problems) else 0


if __name__ == "__main__":
    sys.exit(main())

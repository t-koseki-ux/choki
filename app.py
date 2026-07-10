import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import io
import base64
from streamlit_image_coordinates import streamlit_image_coordinates

# セッションステートの初期化（クリックしたY座標を保存）
if "y_coords" not in st.session_state:
    st.session_state.y_coords = []

st.title("PDF自動切り出し＆HTML生成アプリ")

# 1. PDFのアップロード
uploaded_file = st.file_uploader("PDFファイルをアップロードしてください", type=["pdf"])

if uploaded_file is not None:
    # PDFをPyMuPDFで読み込み、1ページ目を画像化
    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc.load_page(0)  # 今回は1ページ目を対象
    pix = page.get_pixmap(dpi=150) # 解像度の設定
    
    # PyMuPDFの画像をPillow(PIL)画像に変換
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    
    # 2. 画像上に赤い水平線を引く
    draw = ImageDraw.Draw(img)
    for y in st.session_state.y_coords:
        draw.line([(0, y), (img.width, y)], fill="red", width=3)

    st.write("画像をクリックして、切り出したい上下の境界線を指定してください（2回クリックで1エリア）")
    
    # 画像を表示し、クリック座標を取得
    value = streamlit_image_coordinates(img, key="pdf_image")
    
    # クリックされたらY座標を保存して再描画
    if value is not None:
        clicked_y = value["y"]
        if clicked_y not in st.session_state.y_coords:
            st.session_state.y_coords.append(clicked_y)
            st.rerun()

    # リセットボタン
    if st.button("引いた線をリセット"):
        st.session_state.y_coords = []
        st.rerun()

    st.markdown("---")

    # 3. 連結と画面パターンの設定
    st.subheader("出力設定")
    concat_images = st.checkbox("切り出した画像を縦に連結する", value=True)
    layout_pattern = st.selectbox("画面パターン（HTMLデザイン）", ["パターンA（中央揃え）", "パターンB（左揃え）", "パターンC（枠線あり）"])

    # 4. 切り出し処理とHTML出力
    if st.button("画像を切り出してHTMLを生成"):
        if len(st.session_state.y_coords) < 2:
            st.error("最低2箇所（上下の境界）をクリックして線を引いてください。")
        else:
            # Y座標を上から順にソート
            sorted_y = sorted(st.session_state.y_coords)
            
            # 2つずつペアにして切り出す
            cropped_images = []
            for i in range(0, len(sorted_y) - 1, 2):
                y_start = sorted_y[i]
                y_end = sorted_y[i+1]
                # (left, upper, right, lower)
                crop_img = img.crop((0, y_start, img.width, y_end))
                cropped_images.append(crop_img)

            final_images = []
            
            # 画像の連結処理
            if concat_images and len(cropped_images) > 1:
                total_height = sum(c.height for c in cropped_images)
                max_width = max(c.width for c in cropped_images)
                dst = Image.new('RGB', (max_width, total_height))
                
                current_y = 0
                for c in cropped_images:
                    dst.paste(c, (0, current_y))
                    current_y += c.height
                final_images.append(dst)
            else:
                final_images = cropped_images

            # HTML生成処理（Base64エンコード）
            img_tags = ""
            for final_img in final_images:
                buffered = io.BytesIO()
                final_img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                img_tags += f'<img src="data:image/png;base64,{img_str}" style="max-width: 100%; height: auto; margin-bottom: 20px;" /><br>\n'

            # パターンに応じたCSSスタイル
            css_style = "text-align: center;" if layout_pattern == "パターンA（中央揃え）" else "text-align: left;"
            if layout_pattern == "パターンC（枠線あり）":
                css_style += " border: 2px solid #333; padding: 20px;"

            html_content = f"""
            <!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                <title>出力結果</title>
            </head>
            <body style="background-color: #f0f0f0; padding: 50px; font-family: sans-serif;">
                <div style="background-color: #fff; padding: 30px; box-shadow: 0 0 10px rgba(0,0,0,0.1); {css_style}">
                    <h2>指定されたパターン: {layout_pattern}</h2>
                    {img_tags}
                </div>
            </body>
            </html>
            """

            # ダウンロードボタンの設置
            st.success("処理が完了しました！以下のボタンからHTMLファイルをダウンロードしてください。")
            st.download_button(
                label="HTMLをダウンロード",
                data=html_content,
                file_name="output.html",
                mime="text/html"
            )

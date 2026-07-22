import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import io
import base64
from streamlit_image_coordinates import streamlit_image_coordinates
import streamlit.components.v1 as components

# --- ファイル変更検知による前回のデータ完全クリア ---
if "file_name" not in st.session_state:
    st.session_state.file_name = None

def reset_session():
    st.session_state.lines_by_page = {}
    st.session_state.current_page = 0
    st.session_state.img_key = 0
    st.session_state.last_coord = None
    st.session_state.generated_html = None
    st.session_state.concat_states = {}

st.set_page_config(layout="wide")
st.title("[PDF自動切り出し＆HTML生成アプリ.8 (指定テンプレート版)]")

uploaded_file = st.file_uploader("PDFファイルをアップロードしてください", type=["pdf"])

if uploaded_file is not None:
    if st.session_state.file_name != uploaded_file.name:
        reset_session()
        st.session_state.file_name = uploaded_file.name
        st.rerun()

    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = doc.page_count

    # --- 左側サイドバー（操作パネル） ---
    with st.sidebar:
        st.header("🛠️ 操作パネル")
        
        st.subheader("ページ移動")
        col_prev, col_next = st.columns(2)
        with col_prev:
            if st.button("◀ 前ページ") and st.session_state.current_page > 0:
                st.session_state.current_page -= 1
                st.rerun()
        with col_next:
            if st.button("次ページ ▶") and st.session_state.current_page < total_pages - 1:
                st.session_state.current_page += 1
                st.rerun()
        
        st.markdown(f"**現在の位置:** {st.session_state.current_page + 1} / {total_pages} ページ")
        st.markdown("---")

        st.subheader("マウスの動作設定")
        action_mode = st.radio("クリック時の動作", ["✒️ 線を引く", "🗑️ 線を消す（線を直接クリック）"])
        
        st.markdown("---")
        st.subheader("線の種類と太さ")
        line_type = st.radio("引く線の種類", ["通常線（境界）", "太赤線（この範囲を除外）"])
        
        thick_size = 0
        if line_type == "太赤線（この範囲を除外）":
            thick_size = st.slider("太赤線の太さ（px）", 10, 200, 40)
        
        st.markdown("---")
        if st.button("現在のページの線をすべてリセット", type="primary"):
            st.session_state.lines_by_page[st.session_state.current_page] = []
            st.session_state.img_key += 1
            st.session_state.generated_html = None
            st.rerun()

        st.markdown("---")
        st.subheader("HTML / メタデータ設定")
        # 🌟 テンプレート用のatomidを入力できるように変更
        atom_id = st.text_input("atomid (JSON用)", value="CMV1J1Z11LI1")

    # --- メインエリア：画像の表示と線引き ---
    if st.session_state.current_page not in st.session_state.lines_by_page:
        st.session_state.lines_by_page[st.session_state.current_page] = []
    
    current_lines = st.session_state.lines_by_page[st.session_state.current_page]

    page = doc.load_page(st.session_state.current_page)
    pix = page.get_pixmap(dpi=150)
    img_original = Image.open(io.BytesIO(pix.tobytes("png")))
    img_display = img_original.convert("RGBA")
    
    overlay = Image.new("RGBA", img_display.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    
    for line in current_lines:
        y = line["y"]
        if line["type"] == "通常線（境界）":
            draw.line([(0, y), (img_display.width, y)], fill=(255, 0, 0, 255), width=3)
        else:
            t = line["thickness"]
            draw.rectangle([(0, y - t//2), (img_display.width, y + t//2)], fill=(255, 0, 0, 100))

    img_display = Image.alpha_composite(img_display, overlay).convert("RGB")

    st.markdown(f"### 📄 プレビュー (ページ {st.session_state.current_page + 1})")
    
    value = streamlit_image_coordinates(
        img_display, 
        key=f"pdf_img_p{st.session_state.current_page}_k{st.session_state.img_key}"
    )
    
    if value is not None:
        coord_str = f"{value['x']}_{value['y']}_{st.session_state.img_key}"
        if st.session_state.last_coord != coord_str:
            st.session_state.last_coord = coord_str
            clicked_y = value["y"]
            
            if "線を引く" in action_mode:
                if not any(l["y"] == clicked_y for l in current_lines):
                    current_lines.append({"y": clicked_y, "type": line_type, "thickness": thick_size})
            
            elif "線を消す" in action_mode:
                closest_i = -1
                min_dist = 20
                for i, l in enumerate(current_lines):
                    dist = abs(l["y"] - clicked_y)
                    if dist < min_dist:
                        min_dist = dist
                        closest_i = i
                if closest_i != -1:
                    current_lines.pop(closest_i)

            st.session_state.lines_by_page[st.session_state.current_page] = sorted(current_lines, key=lambda x: x["y"])
            st.session_state.generated_html = None
            st.rerun()

    st.markdown("---")

    # --- 全ページの切り出しエリア事前計算 ---
    all_areas = []
    for p_num in sorted(st.session_state.lines_by_page.keys()):
        p_lines = st.session_state.lines_by_page[p_num]
        if len(p_lines) < 2:
            continue
            
        p = doc.load_page(p_num)
        p_pix = p.get_pixmap(dpi=150)
        p_orig = Image.open(io.BytesIO(p_pix.tobytes("png")))
        
        for i in range(len(p_lines) - 1):
            line_a = p_lines[i]
            line_b = p_lines[i+1]
            
            y_start = line_a["y"] + (line_a["thickness"] // 2 if line_a["type"] != "通常線（境界）" else 0)
            y_end = line_b["y"] - (line_b["thickness"] // 2 if line_b["type"] != "通常線（境界）" else 0)
            
            if y_start < y_end:
                crop_img = p_orig.crop((0, y_start, p_orig.width, y_end))
                all_areas.append({
                    "p_num": p_num,
                    "y_start": y_start,
                    "y_end": y_end,
                    "img": crop_img
                })

    # --- 🔗 コンテナを用いた視覚的・直感的な連結UI ---
    if all_areas:
        st.subheader("🔗 切り出しエリアの視覚的連結設定")
        st.write("同じ外枠（コンテナ）に囲まれている画像同士が縦に連結されます。画像間のボタンで直感的に結合・解除が可能です。")
        
        visual_groups = []
        current_g = [all_areas[0]]
        current_idxs = [0]
        
        for idx in range(len(all_areas) - 1):
            area = all_areas[idx]
            state_key = f"link_{area['p_num']}_{int(area['y_start'])}"
            if st.session_state.concat_states.get(state_key, False):
                current_g.append(all_areas[idx+1])
                current_idxs.append(idx+1)
            else:
                visual_groups.append({"areas": current_g, "idxs": current_idxs})
                current_g = [all_areas[idx+1]]
                current_idxs = [idx+1]
        visual_groups.append({"areas": current_g, "idxs": current_idxs})
        
        for g_idx, group in enumerate(visual_groups):
            areas = group["areas"]
            idxs = group["idxs"]
            
            with st.container(border=True):
                if len(areas) > 1:
                    st.markdown(f"<span style='color:#e74c3c; font-weight:bold; background-color:#fadbd8; padding:3px 10px; border-radius:4px;'>🔗 連結中（画像 {idxs[0]+1} ～ {idxs[-1]+1} の結合ブロック）</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<span style='color:#34495e; font-weight:bold; background-color:#eaeded; padding:3px 10px; border-radius:4px;'>■ 単独（画像 {idxs[0]+1}）</span>", unsafe_allow_html=True)
                
                for m_idx, area in enumerate(areas):
                    st.caption(f"画像 {idxs[m_idx]+1} (ページ {area['p_num']+1})")
                    st.image(area['img'], width=350)
                    
                    if m_idx < len(areas) - 1:
                        state_key = f"link_{area['p_num']}_{int(area['y_start'])}"
                        col_un1, col_un2 = st.columns([1, 4])
                        with col_un1:
                            if st.button("🔓 連結解除", key=f"btn_unlink_{idxs[m_idx]}"):
                                st.session_state.concat_states[state_key] = False
                                st.session_state.generated_html = None
                                st.rerun()
            
            if g_idx < len(visual_groups) - 1:
                last_area_in_group = areas[-1]
                last_global_idx = idxs[-1]
                state_key = f"link_{last_area_in_group['p_num']}_{int(last_area_in_group['y_start'])}"
                
                col_b1, col_b2, col_b3 = st.columns([1, 2, 1])
                with col_b2:
                    if st.button(f"⬇️ 上の「画像 {last_global_idx+1}」と 下の「画像 {last_global_idx+2}」を連結する ⬇️", key=f"btn_link_{last_global_idx}"):
                        st.session_state.concat_states[state_key] = True
                        st.session_state.generated_html = None
                        st.rerun()
                        
        st.markdown("---")

    # --- 🚀 データ生成とプレビュー ---
    st.subheader("🚀 データ生成とプレビュー")
    col_pdf, col_html = st.columns(2)
    
    with col_pdf:
        if any(len(lines) > 0 for lines in st.session_state.lines_by_page.values()):
            if st.button("📥 全ページの赤入れPDFを生成"):
                pdf_pages = []
                for p_num in range(total_pages):
                    p = doc.load_page(p_num)
                    p_pix = p.get_pixmap(dpi=150)
                    p_img = Image.open(io.BytesIO(p_pix.tobytes("png"))).convert("RGBA")
                    
                    if p_num in st.session_state.lines_by_page and st.session_state.lines_by_page[p_num]:
                        p_overlay = Image.new("RGBA", p_img.size, (255, 255, 255, 0))
                        p_draw = ImageDraw.Draw(p_overlay)
                        for line in st.session_state.lines_by_page[p_num]:
                            y = line["y"]
                            if line["type"] == "通常線（境界）":
                                p_draw.line([(0, y), (p_img.width, y)], fill=(255, 0, 0, 255), width=3)
                            else:
                                t = line["thickness"]
                                p_draw.rectangle([(0, y - t//2), (p_img.width, y + t//2)], fill=(255, 0, 0, 100))
                        p_img = Image.alpha_composite(p_img, p_overlay)
                    pdf_pages.append(p_img.convert("RGB"))
                
                pdf_buffer = io.BytesIO()
                pdf_pages[0].save(pdf_buffer, format="PDF", save_all=True, append_images=pdf_pages[1:], resolution=150)
                st.download_button("赤入れPDFをダウンロードする", data=pdf_buffer.getvalue(), file_name="annotated.pdf")

    with col_html:
        if st.button("💻 選択した設定でHTMLを生成・更新する", type="primary"):
            if not all_areas:
                st.error("有効な切り出しエリアがありません。線を引き直してください。")
            else:
                img_tags = ""
                for group in visual_groups:
                    imgs = [a["img"] for a in group["areas"]]
                    
                    # 連結処理
                    if len(imgs) > 1:
                        total_height = sum(c.height for c in imgs)
                        max_width = max(c.width for c in imgs)
                        dst = Image.new('RGB', (max_width, total_height))
                        current_y = 0
                        for c in imgs:
                            dst.paste(c, (0, current_y))
                            current_y += c.height
                        final_img = dst
                    else:
                        final_img = imgs[0]
                    
                    # 🌟 自動計算と画像エンコード (WebP & PNG)
                    width, height = final_img.size
                    aspect_ratio = f"{width}/{height}"
                    
                    buffered_png = io.BytesIO()
                    final_img.save(buffered_png, format="PNG")
                    png_str = base64.b64encode(buffered_png.getvalue()).decode()
                    png_uri = f"data:image/png;base64,{png_str}"
                    
                    buffered_webp = io.BytesIO()
                    final_img.save(buffered_webp, format="WEBP")
                    webp_str = base64.b64encode(buffered_webp.getvalue()).decode()
                    webp_uri = f"data:image/webp;base64,{webp_str}"

                    # 🌟 ご指定のセクションテンプレート
                    img_tags += f"""		<section class="box-shadow-1dp">
			<p>
				<picture>
					<source srcset="{webp_uri}" type="image/webp">
					<img src="{png_uri}" style="aspect-ratio: {aspect_ratio};">
				</picture>
			</p>
		</section>\n"""

                # 🌟 ご指定のHTML全体テンプレート
                st.session_state.generated_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width,initial-scale=1.0,minimum-scale=1.0">
	<meta http-equiv="X-UA-Compatible" content="IE=edge">
	<title>Ｚ会学習アプリ</title>
	<link rel="stylesheet" href="../../css/reset.min.css">
	<link rel="stylesheet" href="../../css/base.min.css">
	<link rel="stylesheet" href="../../css/custom_main.min.css" />
	<script type="application/json" id="contentsMetadata">
		{{
			"atomid": "{atom_id}",
			"style": "read-only",
			"answer": "",
			"version": "1"
		}}
	</script>
</head>
<body>
	<main class="box-margin">
{img_tags}	</main>
	<script src="../../contentsInterface/ContentsInterface.js"></script>
	<script src="../../js/lib/jquery.min.js"></script>
	<script src="../../js/lib/jquery-ui.min.js"></script>
	<script src="../../js/lib/jquery.ui.touch-punch.min.js"></script>
	<script src="../../js/custom.min.js"></script>
	<script src="../../js/answer_main.min.js"></script>
	<script src="../../js/zkai_webfont.js"></script>
</body>
</html>"""
                st.rerun()

    if st.session_state.generated_html is not None:
        st.markdown("---")
        st.subheader("🖥️ 生成されたHTMLのリアルタイムプレビュー")
        st.caption("※相対パス（../../css/等）のスタイルシートはプレビュー画面上では読み込まれないため、CSSが外れた状態で表示されますが、ダウンロード後のファイルでは正常に適用されます。")
        components.html(st.session_state.generated_html, height=800, scrolling=True)
        
        st.download_button(
            label="📄 この内容でHTMLファイルを最終保存（PCへダウンロード）",
            data=st.session_state.generated_html,
            file_name="output.html",
            mime="text/html"
        )
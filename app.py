import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageChops
import io
import base64
import zipfile
import json
from streamlit_image_coordinates import streamlit_image_coordinates
import streamlit.components.v1 as components

# --- 余白自動トリミング関数（強化版） ---
def trim_vertical_white_space(img, threshold=245):
    rgb_img = img.convert("RGB")
    gray = rgb_img.convert("L")
    bw = gray.point(lambda x: 0 if x >= threshold else 255)
    bbox = bw.getbbox()
    if bbox:
        return img.crop((0, bbox[1], img.width, bbox[3]))
    return img

if "file_name" not in st.session_state:
    st.session_state.file_name = None
# 🌟 PDF画像のキャッシュ用ステートを追加
if "page_images" not in st.session_state:
    st.session_state.page_images = {}

def reset_session():
    st.session_state.lines_by_page = {}
    st.session_state.current_page = 0
    st.session_state.img_key = 0
    st.session_state.last_coord = None
    st.session_state.preview_html = None
    st.session_state.zip_data = None
    st.session_state.concat_states = {}
    st.session_state.role_states = {}
    st.session_state.app_phase = "drawing" 
    st.session_state.page_images = {} # 🌟 キャッシュもリセット

st.set_page_config(layout="wide")
st.title("[PDF自動切り出し＆HTML生成アプリ.19]")

uploaded_file = st.file_uploader("PDFファイルをアップロードしてください", type=["pdf"])

if uploaded_file is not None:
    if st.session_state.file_name != uploaded_file.name:
        reset_session()
        st.session_state.file_name = uploaded_file.name
        st.rerun()

    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = doc.page_count

    # --- 操作パネル ---
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
            st.session_state.preview_html = None
            st.session_state.zip_data = None
            st.session_state.app_phase = "drawing"
            st.rerun()

        st.markdown("---")
        st.subheader("出力設定")
        output_dpi = st.slider("出力画像の画質 (DPI)", min_value=150, max_value=600, value=300, step=50)
        st.caption("※数値を上げると文字がくっきりしますが、ファイルサイズが重くなります。")
        
        st.markdown("---")
        st.subheader("出力テンプレート設定")
        template_type = st.radio("テンプレートの種類", ["読み物 (通常)", "択一問題 (単一選択)", "スライド式 (ストーリー)"])
        atom_id = st.text_input("atomid (JSON用等)", value="CMV1J1Z12MI4")
        
        concat_margin = st.slider("画像結合時の間の空白サイズ（px）", 0, 100, 20)
        
        correct_answer = ""
        if template_type == "択一問題 (単一選択)":
            correct_answer = st.text_input("正答 (例: 101)", value="101")

    # --- メインエリア：画像の表示と線引き ---
    if st.session_state.current_page not in st.session_state.lines_by_page:
        st.session_state.lines_by_page[st.session_state.current_page] = []
    current_lines = st.session_state.lines_by_page[st.session_state.current_page]

    # 🌟 【劇的軽量化】表示用ベース画像のキャッシュ（毎回PDFから生成しない）
    if st.session_state.current_page not in st.session_state.page_images:
        page = doc.load_page(st.session_state.current_page)
        pix = page.get_pixmap(dpi=150)
        st.session_state.page_images[st.session_state.current_page] = Image.open(io.BytesIO(pix.tobytes("png")))
    
    # キャッシュした画像をコピーして使う
    img_original = st.session_state.page_images[st.session_state.current_page]
    img_display = img_original.copy().convert("RGBA")
    
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
    
    # クリック時の処理
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
            st.session_state.preview_html = None
            st.session_state.zip_data = None
            st.session_state.app_phase = "drawing"
            st.rerun()

    st.markdown("---")

    # ==========================================
    # フェーズごとのフロー制御
    # ==========================================
    
    # ✒️ 線引きフェーズ
    if st.session_state.app_phase == "drawing":
        st.info("👆 上の画像をクリックして赤線を引いてください。線を引き終えたら、下のボタンを押してください。")
        if st.button("✂️ 線の指定を完了し、切り出しエリア設定に進む", type="primary", use_container_width=True):
            has_area = any(len(lines) >= 2 for lines in st.session_state.lines_by_page.values())
            if has_area:
                st.session_state.app_phase = "setting"
                st.rerun()
            else:
                st.error("有効な切り出しエリアがありません。少なくとも1つのページで2本以上の線を引いてください。")

    # 🧩 設定・出力フェーズ
    elif st.session_state.app_phase == "setting":
        if st.button("✏️ 線の指定（引き直し）に戻る"):
            st.session_state.app_phase = "drawing"
            st.rerun()
            
        st.markdown("---")
        
        # 150dpiから高画質dpiへの変換係数
        scale_factor = output_dpi / 150.0
        
        all_areas = []
        with st.spinner(f"高画質（{output_dpi} dpi）で画像を切り出し中です..."):
            for p_num in sorted(st.session_state.lines_by_page.keys()):
                p_lines = st.session_state.lines_by_page[p_num]
                if len(p_lines) < 2:
                    continue
                    
                p = doc.load_page(p_num)
                p_pix = p.get_pixmap(dpi=output_dpi) 
                p_orig = Image.open(io.BytesIO(p_pix.tobytes("png")))
                
                for i in range(len(p_lines) - 1):
                    line_a = p_lines[i]
                    line_b = p_lines[i+1]
                    y_start_150 = line_a["y"] + (line_a["thickness"] // 2 if line_a["type"] != "通常線（境界）" else 0)
                    y_end_150 = line_b["y"] - (line_b["thickness"] // 2 if line_b["type"] != "通常線（境界）" else 0)
                    
                    if y_start_150 < y_end_150:
                        y_start = int(y_start_150 * scale_factor)
                        y_end = int(y_end_150 * scale_factor)
                        
                        crop_img = p_orig.crop((0, y_start, p_orig.width, y_end))
                        crop_img = trim_vertical_white_space(crop_img)
                        
                        all_areas.append({
                            "id": f"img_{p_num}_{int(y_start_150)}",
                            "p_num": p_num,
                            "y_start": y_start_150,
                            "img": crop_img
                        })

        if all_areas:
            st.subheader("🧩 切り出しエリアの設定")
            
            if template_type == "読み物 (通常)":
                st.write("同じ外枠に囲まれている画像同士が縦に連結されます。")
                visual_groups = []
                current_g = [all_areas[0]]
                current_idxs = [0]
                
                for idx in range(len(all_areas) - 1):
                    area = all_areas[idx]
                    state_key = f"link_{area['id']}"
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
                        for m_idx, area in enumerate(areas):
                            st.caption(f"画像 {idxs[m_idx]+1}")
                            st.image(area['img'], width=350)
                            if m_idx < len(areas) - 1:
                                if st.button("🔓 連結解除", key=f"btn_unlink_{idxs[m_idx]}"):
                                    st.session_state.concat_states[f"link_{area['id']}"] = False
                                    st.rerun()
                    if g_idx < len(visual_groups) - 1:
                        last_area = areas[-1]
                        if st.button(f"⬇️ 連結する ⬇️", key=f"btn_link_{idxs[-1]}"):
                            st.session_state.concat_states[f"link_{last_area['id']}"] = True
                            st.rerun()

            else:
                if template_type == "択一問題 (単一選択)":
                    roles_options = ["除外する", "設問", "選択肢 (101)", "選択肢 (102)", "選択肢 (103)", "選択肢 (104)", "解答", "解説"]
                elif template_type == "スライド式 (ストーリー)":
                    roles_options = ["除外する", "全体の問題文"]
                    for i in range(1, 11):
                        roles_options.extend([f"スライド{i}: 設問", f"スライド{i}: 解答", f"スライド{i}: 解説"])
                
                for idx, area in enumerate(all_areas):
                    with st.container(border=True):
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            st.image(area['img'], width=250)
                        with col2:
                            state_key = f"role_{area['id']}"
                            if state_key not in st.session_state.role_states:
                                st.session_state.role_states[state_key] = roles_options[0]
                            
                            selected_role = st.selectbox(
                                f"画像 {idx+1} の役割", 
                                roles_options, 
                                index=roles_options.index(st.session_state.role_states[state_key]) if st.session_state.role_states[state_key] in roles_options else 0,
                                key=f"sb_{state_key}"
                            )
                            st.session_state.role_states[state_key] = selected_role

        st.markdown("---")
        
        # --- データ生成とHTML出力 ---
        st.subheader("🚀 HTML生成とプレビュー")
        if st.button("💻 プレビュー更新＆ZIP生成", type="primary"):
            if not all_areas:
                st.error("有効な切り出しエリアがありません。")
            else:
                zip_buffer = io.BytesIO()
                zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
                folder_name = atom_id
                
                meta_data = {
                    "resource": {
                        "contents_id": atom_id,
                        "pen_tool_status": "2"
                    }
                }
                zip_file.writestr(f"{folder_name}/meta/meta.json", json.dumps(meta_data, indent=4))

                def img_to_html_tags_base64(img):
                    w, h = img.size
                    b_png = io.BytesIO()
                    img.save(b_png, format="PNG")
                    png_uri = f"data:image/png;base64,{base64.b64encode(b_png.getvalue()).decode()}"
                    
                    b_webp = io.BytesIO()
                    img.save(b_webp, format="WEBP")
                    webp_uri = f"data:image/webp;base64,{base64.b64encode(b_webp.getvalue()).decode()}"
                    
                    return f'<picture>\n<source srcset="{webp_uri}" type="image/webp"><img src="{png_uri}" style="aspect-ratio: {w}/{h};">\n</picture>'

                def process_image_for_zip(img, seq_num):
                    base_name = f"{atom_id}{seq_num:03d}"
                    w, h = img.size
                    
                    b_png = io.BytesIO()
                    img.save(b_png, format="PNG")
                    zip_file.writestr(f"{folder_name}/images/{base_name}.png", b_png.getvalue())
                    
                    b_webp = io.BytesIO()
                    img.save(b_webp, format="WEBP")
                    zip_file.writestr(f"{folder_name}/images/{base_name}.png.webp", b_webp.getvalue())
                    
                    return f'<picture>\n<source srcset="./images/{base_name}.png.webp" type="image/webp"><img src="./images/{base_name}.png" style="aspect-ratio: {w}/{h};">\n</picture>'

                def concat_images_vertically(img_list):
                    if not img_list: return None
                    if len(img_list) == 1: return img_list[0]
                    actual_margin = int(concat_margin * scale_factor)
                    max_w = max(img.width for img in img_list)
                    sum_h = sum(img.height for img in img_list) + actual_margin * (len(img_list) - 1)
                    dst = Image.new('RGB', (max_w, sum_h), (255, 255, 255))
                    cy = 0
                    for img in img_list:
                        dst.paste(img, (0, cy))
                        cy += img.height + actual_margin
                    return dst

                seq_num = 10
                html_body_preview = ""
                html_body_dl = ""
                
                style_type = "read-only"
                ans_metadata = '""'

                if template_type == "読み物 (通常)":
                    for group in visual_groups:
                        imgs = [a["img"] for a in group["areas"]]
                        final_img = concat_images_vertically(imgs) if len(imgs) > 1 else imgs[0]
                        
                        p_tag = img_to_html_tags_base64(final_img)
                        d_tag = process_image_for_zip(final_img, seq_num)
                        
                        html_body_preview += f'<section class="box-shadow-1dp">\n<p>\n{p_tag}\n</p>\n</section>\n'
                        html_body_dl += f'<section class="box-shadow-1dp">\n<p>\n{d_tag}\n</p>\n</section>\n'
                        seq_num += 10

                elif template_type == "択一問題 (単一選択)":
                    style_type = "single-choice"
                    ans_metadata = f'["{correct_answer}"]'
                    
                    role_images_lists = {}
                    for area in all_areas:
                        role = st.session_state.role_states.get(f"role_{area['id']}", "除外する")
                        if role not in role_images_lists: role_images_lists[role] = []
                        role_images_lists[role].append(area['img'])
                    role_images = {r: concat_images_vertically(imgs) for r, imgs in role_images_lists.items()}

                    def get_tags(r_name, cur_seq):
                        if r_name in role_images:
                            return img_to_html_tags_base64(role_images[r_name]), process_image_for_zip(role_images[r_name], cur_seq), cur_seq + 10
                        return "", "", cur_seq

                    p_q, d_q, seq_num = get_tags("設問", seq_num)
                    p_ans, d_ans, seq_num = get_tags("解答", seq_num)
                    p_exp, d_exp, seq_num = get_tags("解説", seq_num)

                    p_choices = ""
                    d_choices = ""
                    for val in ["101", "102", "103", "104"]:
                        p_c, d_c, seq_num = get_tags(f"選択肢 ({val})", seq_num)
                        if p_c:
                            p_choices += f'<li><input type="radio" name="radio-01" value="{val}"><label>{p_c}</label></li>\n'
                            d_choices += f'<li><input type="radio" name="radio-01" value="{val}"><label>{d_c}</label></li>\n'

                    html_body_preview = f'''<section class="box-shadow-1dp" id="boxSubQuestion"><div class="box-collapse-header"><h2>設問</h2></div><div class="box-collapsible">
<p>\n{p_q}</p><ul class="sel-item-border lst-img-radio">{p_choices}</ul></div></section>
<section class="box-btn-answer" id="boxBtnAnswer"><button type="button" class="btn-set-next btn-std box-shadow-2dp" id="btnAnswer">解答する</button></section>
<section class="box-shadow-1dp no-disp" id="boxAnswer"><div class="box-collapse-header"><h2>解答</h2></div><div class="box-collapsible">
<p>\n{p_ans}</p><h2>解説</h2><p>\n{p_exp}</p></div></section>'''
                    
                    html_body_dl = f'''<section class="box-shadow-1dp" id="boxSubQuestion"><div class="box-collapse-header"><h2>設問</h2></div><div class="box-collapsible">
<p>\n{d_q}</p><ul class="sel-item-border lst-img-radio">{d_choices}</ul></div></section>
<section class="box-btn-answer" id="boxBtnAnswer"><button type="button" class="btn-set-next btn-std box-shadow-2dp" id="btnAnswer">解答する</button></section>
<section class="box-shadow-1dp no-disp" id="boxAnswer"><div class="box-collapse-header"><h2>解答</h2></div><div class="box-collapsible">
<p>\n{d_ans}</p><h2>解説</h2><p>\n{d_exp}</p></div></section>'''

                elif template_type == "スライド式 (ストーリー)":
                    style_type = "read-only"
                    ans_metadata = '""'
                    
                    role_images_lists = {}
                    for area in all_areas:
                        role = st.session_state.role_states.get(f"role_{area['id']}", "除外する")
                        if role not in role_images_lists: role_images_lists[role] = []
                        role_images_lists[role].append(area['img'])
                    role_images = {r: concat_images_vertically(imgs) for r, imgs in role_images_lists.items()}

                    def get_tags_fixed(r_name, specific_seq):
                        if r_name in role_images:
                            return img_to_html_tags_base64(role_images[r_name]), process_image_for_zip(role_images[r_name], specific_seq)
                        return "", ""

                    p_g, d_g = get_tags_fixed("全体の問題文", 41)
                    
                    def make_global(tag):
                        if tag:
                            return f'''<section class="box-shadow-1dp">
<div class="box-collapse-header box-expand"><h2>問題文</h2></div>
<div class="box-collapsible"><p>\n{tag}</p></div></section>\n'''
                        return ""
                    
                    p_slides_html = ""
                    d_slides_html = ""
                    max_slide = 0
                    for role in role_images.keys():
                        if role.startswith("スライド"):
                            try:
                                max_slide = max(max_slide, int(role.split("スライド")[1].split(":")[0]))
                            except: pass

                    for i in range(1, max_slide + 1):
                        p_sq, d_sq = get_tags_fixed(f"スライド{i}: 設問", 50 + i)
                        p_sa, d_sa = get_tags_fixed(f"スライド{i}: 解答", 70 + i)
                        p_se, d_se = get_tags_fixed(f"スライド{i}: 解説", 80 + i)

                        if not p_sq and not p_sa and not p_se: continue

                        li_class = ' class="lst-current"' if i == 1 else ''
                        
                        def build_li(q, a, e):
                            res = f'<li{li_class}>\n'
                            if q: res += f'<section class="box-shadow-1dp"><div class="box-collapse-header"><h2>設問</h2></div><div class="box-collapsible"><p>\n{q}</p></div></section>\n'
                            if a or e:
                                res += '<section class="box-shadow-1dp"><div class="box-collapse-header"><h2>解答</h2></div><div class="box-collapsible">\n'
                                if a: res += f'<p>\n{a}</p>\n'
                                if e: res += f'<h2>解説</h2>\n<p>\n{e}</p>\n'
                                res += '</div></section>\n'
                            res += '</li>\n'
                            return res

                        p_slides_html += build_li(p_sq, p_sa, p_se)
                        d_slides_html += build_li(d_sq, d_sa, d_se)

                    btn_controls = '''<section class="box-btn-show-picture">
<button type="button" class="box-shadow-2dp btn-show-picture-prev">◀ 前へ</button>
<span class="txt-picture-current"></span> / <span class="txt-picture-length"></span>
<button type="button" class="box-shadow-2dp btn-show-picture-next">次へ ▶</button>
</section>\n'''

                    html_body_preview = f"{make_global(p_g)}{btn_controls}<ul class=\"lst-pic-story\" id=\"lstPicStory\">\n{p_slides_html}</ul>\n{btn_controls}"
                    html_body_dl = f"{make_global(d_g)}{btn_controls}<ul class=\"lst-pic-story\" id=\"lstPicStory\">\n{d_slides_html}</ul>\n{btn_controls}"

                def build_full_html(body_content):
                    return f"""<!DOCTYPE html>
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
"style": "{style_type}",
"answer": {ans_metadata},
"version": "1"
}}
</script>
</head>
<body>
<main class="box-margin">
{body_content}</main>
<script src="../../contentsInterface/ContentsInterface.js"></script>
<script src="../../js/lib/jquery.min.js"></script>
<script src="../../js/lib/jquery-ui.min.js"></script>
<script src="../../js/lib/jquery.ui.touch-punch.min.js"></script>
<script src="../../js/custom.min.js"></script>
<script src="../../js/answer_main.min.js"></script>
<script src="../../js/zkai_webfont.js"></script>
</body>
</html>"""

                dl_full_html = build_full_html(html_body_dl)
                zip_file.writestr(f"{folder_name}/index.html", dl_full_html.encode("utf-8"))
                zip_file.close()
                st.session_state.zip_data = zip_buffer.getvalue()

                preview_fallback = """
<style>
#lstPicStory { list-style: none; padding: 0; margin: 0; }
#lstPicStory > li { display: none; }
#lstPicStory > li.lst-current { display: block; }
.box-btn-show-picture { display: flex; align-items: center; justify-content: center; gap: 15px; margin: 20px 0; font-size: 1.2rem; font-weight: bold; }
.btn-show-picture-prev, .btn-show-picture-next { cursor: pointer; padding: 8px 16px; border: 1px solid #ccc; background: #fff; border-radius: 4px; }
.box-collapse-header { cursor: pointer; background: #f5f5f5; padding: 10px; border-bottom: 1px solid #ddd; margin-top: 10px; }
.no-disp { display: none !important; }
</style>
<script>
document.addEventListener('DOMContentLoaded', function() {
    const lis = document.querySelectorAll('#lstPicStory > li');
    const len = lis.length;
    let currentIdx = 0;
    function updateSlide() {
        lis.forEach((li, idx) => {
            if (idx === currentIdx) {
                li.classList.add('lst-current');
                li.style.display = 'block';
            } else {
                li.classList.remove('lst-current');
                li.style.display = 'none';
            }
        });
        document.querySelectorAll('.txt-picture-current').forEach(el => el.textContent = currentIdx + 1);
        document.querySelectorAll('.txt-picture-length').forEach(el => el.textContent = len);
    }
    if (len > 0) {
        document.querySelectorAll('.btn-show-picture-prev').forEach(btn => {
            btn.addEventListener('click', () => { if (currentIdx > 0) { currentIdx--; updateSlide(); } });
        });
        document.querySelectorAll('.btn-show-picture-next').forEach(btn => {
            btn.addEventListener('click', () => { if (currentIdx < len - 1) { currentIdx++; updateSlide(); } });
        });
        updateSlide();
    }

    document.querySelectorAll('.box-collapse-header').forEach(header => {
        header.addEventListener('click', function() {
            const content = this.nextElementSibling;
            if(content && content.classList.contains('box-collapsible')) {
                content.classList.toggle('no-disp');
            }
        });
    });
    
    const btnAnswer = document.getElementById('btnAnswer');
    if (btnAnswer) {
        btnAnswer.addEventListener('click', function() {
            const boxAnswer = document.getElementById('boxAnswer');
            if (boxAnswer) boxAnswer.classList.remove('no-disp');
        });
    }
});
</script>
</body></html>"""
                st.session_state.preview_html = build_full_html(html_body_preview).replace('</body>\n</html>', preview_fallback)

        # --- プレビュー表示とダウンロードボタン ---
        if st.session_state.preview_html is not None and st.session_state.zip_data is not None:
            st.markdown("---")
            components.html(st.session_state.preview_html, height=800, scrolling=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="📦 ZIPファイル一括ダウンロード (本番仕様)",
                    data=st.session_state.zip_data,
                    file_name=f"{atom_id}.zip",
                    mime="application/zip"
                )

        # --- 編集済みPDFのダウンロード機能 ---
        st.markdown("---")
        st.subheader("📥 編集済みPDFのダウンロード")
        st.write("画面上で引いた赤線や太赤線の領域を、元のPDFに直接書き込んで保存します。")
        
        out_pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        scale = 72 / 150  
        
        for p_num, lines in st.session_state.lines_by_page.items():
            if lines:
                out_page = out_pdf.load_page(p_num)
                for line in lines:
                    y_px = line["y"]
                    y_pt = y_px * scale
                    if line["type"] == "通常線（境界）":
                        p1 = fitz.Point(0, y_pt)
                        p2 = fitz.Point(out_page.rect.width, y_pt)
                        out_page.draw_line(p1, p2, color=(1, 0, 0), width=2)
                    else:
                        t_px = line["thickness"]
                        t_pt = t_px * scale
                        rect = fitz.Rect(0, y_pt - t_pt/2, out_page.rect.width, y_pt + t_pt/2)
                        shape = out_page.new_shape()
                        shape.draw_rect(rect)
                        shape.finish(color=None, fill=(1, 0, 0), fill_opacity=0.3)
                        shape.commit()

        pdf_out_bytes = out_pdf.tobytes()
        st.download_button(
            label="📄 赤線を引いたPDFをダウンロード",
            data=pdf_out_bytes,
            file_name=f"annotated_{st.session_state.file_name}",
            mime="application/pdf"
        )
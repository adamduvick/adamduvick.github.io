def on_post_page(output_content, **kwargs):
    return output_content.replace("..\\scripts\\", "../scripts/")
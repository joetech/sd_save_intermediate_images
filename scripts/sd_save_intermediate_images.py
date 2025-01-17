import os

from modules import scripts
from modules.processing import Processed, process_images, fix_seed, create_infotext
from modules.sd_samplers import KDiffusionSampler, sample_to_image
from modules.images import save_image, FilenameGenerator, get_next_sequence_number
from modules.shared import opts, state

import gradio as gr

orig_callback_state = KDiffusionSampler.callback_state

class Script(scripts.Script):
    def title(self):
        return "Save intermediate images during the sampling process"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Group():
            with gr.Accordion("Save intermediate images", open=False):
                with gr.Group():
                    is_active = gr.Checkbox(
                        label="Save intermediate images",
                        value=False
                    )
                with gr.Group():
                    intermediate_type = gr.Radio(
                        label="Should the intermediate images be denoised or noisy?",
                        choices=["Denoised", "Noisy"],
                        value="Denoised"
                    )
                with gr.Group():
                    every_n = gr.Number(
                        label="Save every N images",
                        value="5"
                    )
                with gr.Group():
                    stop_at_n = gr.Number(
                        label="Stop at N images (must be 0 = don't stop early or a multiple of 'Save every N images')",
                        value="0"
                    )
        return [is_active, intermediate_type, every_n, stop_at_n]

    def save_image_only_get_name(image, path, basename, seed=None, prompt=None, extension='png', info=None, short_filename=False, no_prompt=False, grid=False, pnginfo_section_name='parameters', p=None, existing_info=None, forced_filename=None, suffix="", save_to_dirs=None):
        #for description see modules.images.save_image, same code up saving of files
        
        namegen = FilenameGenerator(p, seed, prompt, image)

        if save_to_dirs is None:
            save_to_dirs = (grid and opts.grid_save_to_dirs) or (not grid and opts.save_to_dirs and not no_prompt)

        if save_to_dirs:
            dirname = namegen.apply(opts.directories_filename_pattern or "[prompt_words]").lstrip(' ').rstrip('\\ /')
            path = os.path.join(path, dirname)

        os.makedirs(path, exist_ok=True)

        if forced_filename is None:
            if short_filename or seed is None:
                file_decoration = ""
            elif opts.save_to_dirs:
                file_decoration = opts.samples_filename_pattern or "[seed]"
            else:
                file_decoration = opts.samples_filename_pattern or "[seed]-[prompt_spaces]"

            add_number = opts.save_images_add_number or file_decoration == ''

            if file_decoration != "" and add_number:
                file_decoration = "-" + file_decoration

            file_decoration = namegen.apply(file_decoration) + suffix

            if add_number:
                basecount = get_next_sequence_number(path, basename)
                fullfn = None
                for i in range(500):
                    fn = f"{basecount + i:05}" if basename == '' else f"{basename}-{basecount + i:04}"
                    fullfn = os.path.join(path, f"{fn}{file_decoration}.{extension}")
                    if not os.path.exists(fullfn):
                        break
            else:
                fullfn = os.path.join(path, f"{file_decoration}.{extension}")
        else:
            fullfn = os.path.join(path, f"{forced_filename}.{extension}")

        return (fullfn)

    def process(self, p, is_active, intermediate_type, every_n, stop_at_n):
        if is_active:
            def callback_state(self, d):
                """
                callback_state runs after each processing step
                """
                current_step = d["i"]

                if hasattr(p, "enable_hr"):
                    hr = p.enable_hr
                else:
                    hr = False 

                #Highres. fix requires 2 passes
                if not hasattr(p, 'intermed_final_pass'):
                    if hr:
                        p.intermed_first_pass = True
                        p.intermed_final_pass = False
                    else:
                        p.intermed_first_pass = True
                        p.intermed_final_pass = True

                #Check if pass 1 has finished
                if hasattr(p, 'intermed_max_step'):
                    if current_step >= p.intermed_max_step:
                        p.intermed_max_step = current_step
                    else:
                        p.intermed_first_pass = False
                        p.intermed_final_pass = True
                        p.intermed_max_step = current_step
                else:
                        p.intermed_max_step = current_step

                #stop_at_n must be a multiple of every_n
                if not hasattr(p, 'intermed_stop_at_n'):
                    if stop_at_n % every_n == 0:
                        p.intermed_stop_at_n = stop_at_n
                    else:
                        p.intermed_stop_at_n = int(stop_at_n / every_n) * every_n

                if current_step % every_n == 0:
                    for index in range(0, p.batch_size):
                        if intermediate_type == "Denoised":
                            image = sample_to_image(d["denoised"], index=index)
                        else:
                            image = sample_to_image(d["x"], index=index)

                        # Inits per seed
                        if current_step == 0 and p.intermed_first_pass:
                            if opts.save_images_add_number:
                                digits = 5
                            else:
                                digits = 6
                            if index == 0:
                                # Set custom folder for saving intermediates on first step of first image
                                intermed_path = os.path.join(p.outpath_samples, "intermediates")
                                os.makedirs(intermed_path, exist_ok=True)
                                # Set filename with pattern. Two versions depending on opts.save_images_add_number
                                fullfn = Script.save_image_only_get_name(image, p.outpath_samples, "", int(p.seed), p.prompt, p=p)
                                base_name, _ = os.path.splitext(fullfn)
                                base_name = os.path.basename(base_name)
                                substrings = base_name.split('-')
                                if opts.save_images_add_number:
                                    intermed_number = substrings[0]
                                    intermed_number = f"{intermed_number:0{digits}}"
                                    intermed_suffix = '-'.join(substrings[1:])
                                else:
                                    intermed_number = get_next_sequence_number(intermed_path, "")
                                    intermed_number = f"{intermed_number:0{digits}}"
                                    intermed_suffix = '-'.join(substrings[0:])
                                intermed_path = os.path.join(intermed_path, intermed_number)
                                p.intermed_outpath = intermed_path
                                p.intermed_outpath_number = []
                                p.intermed_outpath_number.append(intermed_number)
                                p.intermed_outpath_suffix = intermed_suffix
                            else:
                                intermed_number = int(p.intermed_outpath_number[0]) + index
                                intermed_number = f"{intermed_number:0{digits}}"
                                p.intermed_outpath_number.append(intermed_number)

                        intermed_suffix = p.intermed_outpath_suffix.replace(str(int(p.seed)), str(int(p.all_seeds[index])), 1)
                        intermed_pattern = p.intermed_outpath_number[index] + "-%%%-" + intermed_suffix
                        if hr:
                            if p.intermed_final_pass:
                                intermed_pattern = intermed_pattern.replace("%%%", "%%%-p2")
                            else:
                                intermed_pattern = intermed_pattern.replace("%%%", "%%%-p1")
                        filename = intermed_pattern.replace("%%%", f"{current_step:03}")

                        #don't save first step
                        if current_step > 0:
                            #generate png-info
                            infotext = create_infotext(p, p.all_prompts, p.all_seeds, p.all_subseeds, comments=[], position_in_batch=index % p.batch_size, iteration=index // p.batch_size)
                            infotext = f'{infotext}, intermediate: {current_step:03d}'

                            if current_step == p.intermed_stop_at_n:
                                if (hr and p.intermed_final_pass) or not hr:
                                    #early stop for this seed reached, prevent normal save, save as final image
                                    p.do_not_save_samples = True
                                    save_image(image, p.outpath_samples, "", p.all_seeds[index], p.prompt, opts.samples_format, info=infotext, p=p)
                                    if index == p.batch_size - 1:
                                        #early stop for final seed and final pass reached, interrupt further processing
                                        state.interrupt()
                                else:
                                    #save intermediate image
                                    save_image(image, p.intermed_outpath, "", info=infotext, p=p, forced_filename=filename)
                            else:
                                #save intermediate image
                                save_image(image, p.intermed_outpath, "", info=infotext, p=p, forced_filename=filename)

                return orig_callback_state(self, d)

            setattr(KDiffusionSampler, "callback_state", callback_state)

    def postprocess(self, p, processed, is_active, intermediate_type, every_n, stop_at_n):
        setattr(KDiffusionSampler, "callback_state", orig_callback_state)

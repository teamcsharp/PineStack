"""#1241: the workflow reader behind the overlays' top panel.

The banner's whole value is that it names the render rather than saying
"busy": the model, the size, the sampler, the steps, and the PROMPT. Every
one of those is dug out of a ComfyUI prompt-dict, and a prompt-dict is a
graph — the sampler does not hold the text, it holds a reference to a node
that holds a reference to a node that does.

So these tests are fixtures of the real graph shapes this box renders, and
they pin the three things that would fail silently and look fine:

  * a forwarding node between the sampler and its text (FluxGuidance is in
    every flux workflow on this machine) — the first version of this reader
    stopped at the first node and returned nothing;
  * the NEGATIVE prompt coming back as the positive one, which no one would
    notice on a banner;
  * the signature, which is what the progress estimate is keyed on. Two
    renders that differ only in seed must share a signature or every render
    looks like the first of its kind and never gets a progress bar.
"""
import unittest

import spark_overlays as so


def sampler_graph(**over):
    """A workflow the shape ComfyUI actually posts: loader, two text nodes,
    an empty latent, a sampler, a save."""
    graph = {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sdxl_base.safetensors"}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "a cat conducting an orchestra"}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "blurry, watermark"}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 28, "cfg": 7.5,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["5", 0], "model": ["4", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "PineBox"}},
    }
    graph.update(over)
    return graph


class WorkflowReadingTests(unittest.TestCase):
    def test_it_names_the_render(self):
        info = so.analyze_workflow(sampler_graph())
        self.assertEqual(info["model"], "sdxl_base.safetensors")
        self.assertEqual(info["width"], 1024)
        self.assertEqual(info["height"], 1024)
        self.assertEqual(info["steps"], 28)
        self.assertEqual(info["cfg"], 7.5)
        self.assertEqual(info["sampler_name"], "dpmpp_2m")
        self.assertEqual(info["scheduler"], "karras")
        self.assertEqual(info["filename_prefix"], "PineBox")
        self.assertEqual(info["nodes"], 6)

    def test_a_unet_workflow_still_has_a_model(self):
        # Flux and Wan graphs load a UNET rather than a checkpoint; a reader
        # that only knew CheckpointLoaderSimple showed a blank model on every
        # one of them.
        graph = sampler_graph()
        del graph["4"]
        graph["37"] = {"class_type": "UNETLoader",
                       "inputs": {"unet_name": "flux1-dev.safetensors"}}
        self.assertEqual(so.analyze_workflow(graph)["model"],
                         "flux1-dev.safetensors")

    def test_loras_are_collected_not_overwritten(self):
        graph = sampler_graph()
        graph["10"] = {"class_type": "LoraLoader",
                       "inputs": {"lora_name": "detail.safetensors"}}
        graph["11"] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"lora_name": "film.safetensors"}}
        self.assertEqual(so.analyze_workflow(graph)["lora_names"],
                         ["detail.safetensors", "film.safetensors"])

    def test_video_length_is_kept(self):
        graph = sampler_graph()
        graph["5"] = {"class_type": "EmptyHunyuanLatentVideo",
                      "inputs": {"width": 848, "height": 480, "length": 49}}
        self.assertEqual(so.analyze_workflow(graph)["length"], 49)

    def test_nonsense_is_an_empty_dict_not_a_crash(self):
        self.assertEqual(so.analyze_workflow(None), {})
        self.assertEqual(so.analyze_workflow("not a graph"), {})
        self.assertEqual(so.analyze_workflow({"1": "not a node"})["nodes"], 1)


class PromptTextTests(unittest.TestCase):
    def test_the_positive_prompt_is_the_positive_one(self):
        graph = sampler_graph()
        self.assertEqual(so.extract_prompt_text(graph, "positive"),
                         "a cat conducting an orchestra")
        self.assertEqual(so.extract_prompt_text(graph, "negative"),
                         "blurry, watermark")

    def test_it_walks_through_a_forwarding_node(self):
        # EVERY flux workflow on this box has a FluxGuidance between the
        # sampler and its text. A reader that gives up at the first hop
        # shows an empty prompt on all of them and looks like ComfyUI sent
        # nothing.
        graph = sampler_graph()
        graph["30"] = {"class_type": "FluxGuidance",
                       "inputs": {"conditioning": ["6", 0], "guidance": 3.5}}
        graph["3"]["inputs"]["positive"] = ["30", 0]
        self.assertEqual(so.extract_prompt_text(graph, "positive"),
                         "a cat conducting an orchestra")

    def test_it_gives_up_rather_than_looping_for_ever(self):
        graph = sampler_graph()
        graph["30"] = {"class_type": "ConditioningCombine",
                       "inputs": {"conditioning": ["30", 0]}}   # points at itself
        graph["3"]["inputs"]["positive"] = ["30", 0]
        # Falls back to a text node rather than spinning: the hop limit is
        # what stops a malformed graph from hanging the poll.
        self.assertEqual(so.extract_prompt_text(graph, "positive"),
                         "a cat conducting an orchestra")

    def test_a_graph_with_no_sampler_still_yields_its_prompt(self):
        # Some image-to-image flows have no KSampler at all.
        graph = {"6": {"class_type": "CLIPTextEncode",
                       "inputs": {"text": "restore this photograph"}}}
        self.assertEqual(so.extract_prompt_text(graph, "positive"),
                         "restore this photograph")
        # ...but there is no negative to fall back to, and inventing one
        # would put the positive prompt under a "negative:" label.
        self.assertIsNone(so.extract_prompt_text(graph, "negative"))


class SignatureTests(unittest.TestCase):
    """The signature is what the progress estimate is keyed on."""

    def test_two_renders_differing_only_in_seed_share_a_signature(self):
        a = sampler_graph()
        b = sampler_graph()
        b["3"]["inputs"]["seed"] = 999
        self.assertEqual(so.workflow_signature(so.analyze_workflow(a)),
                         so.workflow_signature(so.analyze_workflow(b)))

    def test_a_different_size_is_a_different_signature(self):
        a = sampler_graph()
        b = sampler_graph()
        b["5"]["inputs"]["width"] = 512
        self.assertNotEqual(so.workflow_signature(so.analyze_workflow(a)),
                            so.workflow_signature(so.analyze_workflow(b)))

    def test_a_different_step_count_is_a_different_signature(self):
        # Steps are very nearly linear in render time, so timing a 28-step
        # render against a 12-step one would put the bar at 200%.
        a = sampler_graph()
        b = sampler_graph()
        b["3"]["inputs"]["steps"] = 12
        self.assertNotEqual(so.workflow_signature(so.analyze_workflow(a)),
                            so.workflow_signature(so.analyze_workflow(b)))

    def test_an_empty_analysis_has_a_signature_rather_than_a_crash(self):
        self.assertEqual(so.workflow_signature({}), "?")


class OpenWebuiTextTests(unittest.TestCase):
    def test_reasoning_blocks_are_stripped(self):
        # OpenWebUI 0.8.x wraps model reasoning in a collapsible block. The
        # panel shows what a person sees in the chat, not the scaffolding.
        raw = ('<details type="reasoning" done="true"><summary>Thought</summary>'
               'first I should...</details>The answer is 41.')
        self.assertEqual(so.clean_owui_text(raw), "The answer is 41.")

    def test_stray_model_tags_go_too(self):
        self.assertEqual(
            so.clean_owui_text("<think>hmm</think> hello  there"),
            "hmm hello there")

    def test_it_never_returns_none(self):
        self.assertEqual(so.clean_owui_text(None), "")
        self.assertEqual(so.clean_owui_text(42), "")


if __name__ == "__main__":
    unittest.main()

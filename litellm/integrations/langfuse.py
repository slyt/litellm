#### What this does ####
#    On success, logs events to Langfuse
import dotenv, os

dotenv.load_dotenv()  # Loading env variables using dotenv
import copy
import traceback
from packaging.version import Version
from litellm._logging import verbose_logger
import litellm


class LangFuseLogger:
    # Class variables or attributes
    def __init__(
        self, langfuse_public_key=None, langfuse_secret=None, flush_interval=1
    ):
        try:
            from langfuse import Langfuse
            import langfuse
        except Exception as e:
            raise Exception(
                f"\033[91mLangfuse not installed, try running 'pip install langfuse' to fix this error: {e}\n{traceback.format_exc()}\033[0m"
            )
        # Instance variables
        self.secret_key = langfuse_secret or os.getenv("LANGFUSE_SECRET_KEY")
        self.public_key = langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self.langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self.langfuse_release = os.getenv("LANGFUSE_RELEASE")
        self.langfuse_debug = os.getenv("LANGFUSE_DEBUG")

        parameters = {
            "public_key": self.public_key,
            "secret_key": self.secret_key,
            "host": self.langfuse_host,
            "release": self.langfuse_release,
            "debug": self.langfuse_debug,
            "flush_interval": flush_interval,  # flush interval in seconds
        }

        if Version(langfuse.version.__version__) >= Version("2.6.0"):
            parameters["sdk_integration"] = "litellm"

        self.Langfuse = Langfuse(**parameters)

        # set the current langfuse project id in the environ
        # this is used by Alerting to link to the correct project
        try:
            project_id = self.Langfuse.client.projects.get().data[0].id
            os.environ["LANGFUSE_PROJECT_ID"] = project_id
        except:
            project_id = None

        if os.getenv("UPSTREAM_LANGFUSE_SECRET_KEY") is not None:
            self.upstream_langfuse_secret_key = os.getenv(
                "UPSTREAM_LANGFUSE_SECRET_KEY"
            )
            self.upstream_langfuse_public_key = os.getenv(
                "UPSTREAM_LANGFUSE_PUBLIC_KEY"
            )
            self.upstream_langfuse_host = os.getenv("UPSTREAM_LANGFUSE_HOST")
            self.upstream_langfuse_release = os.getenv("UPSTREAM_LANGFUSE_RELEASE")
            self.upstream_langfuse_debug = os.getenv("UPSTREAM_LANGFUSE_DEBUG")
            self.upstream_langfuse = Langfuse(
                public_key=self.upstream_langfuse_public_key,
                secret_key=self.upstream_langfuse_secret_key,
                host=self.upstream_langfuse_host,
                release=self.upstream_langfuse_release,
                debug=self.upstream_langfuse_debug,
            )
        else:
            self.upstream_langfuse = None

    # def log_error(kwargs, response_obj, start_time, end_time):
    #     generation = trace.generation(
    #         level ="ERROR" # can be any of DEBUG, DEFAULT, WARNING or ERROR
    #         status_message='error' # can be any string (e.g. stringified stack trace or error body)
    #     )
    def log_event(
        self,
        kwargs,
        response_obj,
        start_time,
        end_time,
        user_id,
        print_verbose,
        level="DEFAULT",
        status_message=None,
    ) -> dict:
        # Method definition

        try:
            print_verbose(
                f"Langfuse Logging - Enters logging function for model {kwargs}"
            )

            litellm_params = kwargs.get("litellm_params", {})
            metadata = (
                litellm_params.get("metadata", {}) or {}
            )  # if litellm_params['metadata'] == None
            optional_params = copy.deepcopy(kwargs.get("optional_params", {}))

            prompt = {"messages": kwargs.get("messages")}
            functions = optional_params.pop("functions", None)
            tools = optional_params.pop("tools", None)
            if functions is not None:
                prompt["functions"] = functions
            if tools is not None:
                prompt["tools"] = tools

            # langfuse only accepts str, int, bool, float for logging
            for param, value in optional_params.items():
                if not isinstance(value, (str, int, bool, float)):
                    try:
                        optional_params[param] = str(value)
                    except:
                        # if casting value to str fails don't block logging
                        pass

            # end of processing langfuse ########################
            if (
                level == "ERROR"
                and status_message is not None
                and isinstance(status_message, str)
            ):
                input = prompt
                output = status_message
            elif response_obj is not None and (
                kwargs.get("call_type", None) == "embedding"
                or isinstance(response_obj, litellm.EmbeddingResponse)
            ):
                input = prompt
                output = response_obj["data"]
            elif response_obj is not None and isinstance(
                response_obj, litellm.ModelResponse
            ):
                input = prompt
                output = response_obj["choices"][0]["message"].json()
            elif response_obj is not None and isinstance(
                response_obj, litellm.TextCompletionResponse
            ):
                input = prompt
                output = response_obj.choices[0].text
            elif response_obj is not None and isinstance(
                response_obj, litellm.ImageResponse
            ):
                input = prompt
                output = response_obj["data"]
            print_verbose(f"OUTPUT IN LANGFUSE: {output}; original: {response_obj}")
            trace_id = None
            generation_id = None
            if self._is_langfuse_v2():
                trace_id, generation_id = self._log_langfuse_v2(
                    user_id,
                    metadata,
                    litellm_params,
                    output,
                    start_time,
                    end_time,
                    kwargs,
                    optional_params,
                    input,
                    response_obj,
                    level,
                    print_verbose,
                )
            elif response_obj is not None:
                self._log_langfuse_v1(
                    user_id,
                    metadata,
                    output,
                    start_time,
                    end_time,
                    kwargs,
                    optional_params,
                    input,
                    response_obj,
                )
            print_verbose(
                f"Langfuse Layer Logging - final response object: {response_obj}"
            )
            verbose_logger.info(f"Langfuse Layer Logging - logging success")

            return {"trace_id": trace_id, "generation_id": generation_id}
        except:
            traceback.print_exc()
            verbose_logger.debug(f"Langfuse Layer Error - {traceback.format_exc()}")
            return {"trace_id": None, "generation_id": None}

    async def _async_log_event(
        self, kwargs, response_obj, start_time, end_time, user_id, print_verbose
    ):
        """
        TODO: support async calls when langfuse is truly async
        """

    def _is_langfuse_v2(self):
        import langfuse

        return Version(langfuse.version.__version__) >= Version("2.0.0")

    def _log_langfuse_v1(
        self,
        user_id,
        metadata,
        output,
        start_time,
        end_time,
        kwargs,
        optional_params,
        input,
        response_obj,
    ):
        from langfuse.model import CreateTrace, CreateGeneration

        verbose_logger.warning(
            "Please upgrade langfuse to v2.0.0 or higher: https://github.com/langfuse/langfuse-python/releases/tag/v2.0.1"
        )

        trace = self.Langfuse.trace(
            CreateTrace(
                name=metadata.get("generation_name", "litellm-completion"),
                input=input,
                output=output,
                userId=user_id,
            )
        )

        trace.generation(
            CreateGeneration(
                name=metadata.get("generation_name", "litellm-completion"),
                startTime=start_time,
                endTime=end_time,
                model=kwargs["model"],
                modelParameters=optional_params,
                prompt=input,
                completion=output,
                usage={
                    "prompt_tokens": response_obj["usage"]["prompt_tokens"],
                    "completion_tokens": response_obj["usage"]["completion_tokens"],
                },
                metadata=metadata,
            )
        )

    def _log_langfuse_v2(
        self,
        user_id,
        metadata,
        litellm_params,
        output,
        start_time,
        end_time,
        kwargs,
        optional_params,
        input,
        response_obj,
        level,
        print_verbose,
    ) -> tuple:
        import langfuse

        try:
            tags = []
            try:
                metadata = copy.deepcopy(
                    metadata
                )  # Avoid modifying the original metadata
            except:
                new_metadata = {}
                for key, value in metadata.items():
                    if (
                        isinstance(value, list)
                        or isinstance(value, dict)
                        or isinstance(value, str)
                        or isinstance(value, int)
                        or isinstance(value, float)
                    ):
                        new_metadata[key] = copy.deepcopy(value)
                metadata = new_metadata

            supports_tags = Version(langfuse.version.__version__) >= Version("2.6.3")
            supports_prompt = Version(langfuse.version.__version__) >= Version("2.7.3")
            supports_costs = Version(langfuse.version.__version__) >= Version("2.7.3")
            supports_completion_start_time = Version(
                langfuse.version.__version__
            ) >= Version("2.7.3")

            print_verbose(f"Langfuse Layer Logging - logging to langfuse v2 ")

            if supports_tags:
                metadata_tags = metadata.pop("tags", [])
                tags = metadata_tags

            # Clean Metadata before logging - never log raw metadata
            # the raw metadata can contain circular references which leads to infinite recursion
            # we clean out all extra litellm metadata params before logging
            clean_metadata = {}
            if isinstance(metadata, dict):
                for key, value in metadata.items():

                    # generate langfuse tags - Default Tags sent to Langfuse from LiteLLM Proxy
                    if (
                        litellm._langfuse_default_tags is not None
                        and isinstance(litellm._langfuse_default_tags, list)
                        and key in litellm._langfuse_default_tags
                    ):
                        tags.append(f"{key}:{value}")

                    # clean litellm metadata before logging
                    if key in [
                        "headers",
                        "endpoint",
                        "caching_groups",
                        "previous_models",
                    ]:
                        continue
                    else:
                        clean_metadata[key] = value

            session_id = clean_metadata.pop("session_id", None)
            trace_name = clean_metadata.pop("trace_name", None)
            trace_id = clean_metadata.pop("trace_id", None)
            existing_trace_id = clean_metadata.pop("existing_trace_id", None)
            update_trace_keys = clean_metadata.pop("update_trace_keys", [])
            debug = clean_metadata.pop("debug_langfuse", None)

            if trace_name is None and existing_trace_id is None:
                # just log `litellm-{call_type}` as the trace name
                ## DO NOT SET TRACE_NAME if trace-id set. this can lead to overwriting of past traces.
                trace_name = f"litellm-{kwargs.get('call_type', 'completion')}"

            if existing_trace_id is not None:
                trace_params = {"id": existing_trace_id}

                # Update the following keys for this trace
                for metadata_param_key in update_trace_keys:
                    trace_param_key = metadata_param_key.replace("trace_", "")
                    if trace_param_key not in trace_params:
                        updated_trace_value = clean_metadata.pop(
                            metadata_param_key, None
                        )
                        if updated_trace_value is not None:
                            trace_params[trace_param_key] = updated_trace_value

                # Pop the trace specific keys that would have been popped if there were a new trace
                for key in list(
                    filter(lambda key: key.startswith("trace_"), clean_metadata.keys())
                ):
                    clean_metadata.pop(key, None)

                # Special keys that are found in the function arguments and not the metadata
                if "input" in update_trace_keys:
                    trace_params["input"] = input
                if "output" in update_trace_keys:
                    trace_params["output"] = output
            else:  # don't overwrite an existing trace
                trace_params = {
                    "id": trace_id,
                    "name": trace_name,
                    "session_id": session_id,
                    "input": input,
                    "version": clean_metadata.pop(
                        "trace_version", clean_metadata.get("version", None)
                    ),  # If provided just version, it will applied to the trace as well, if applied a trace version it will take precedence
                    "user_id": user_id,
                }
                for key in list(
                    filter(lambda key: key.startswith("trace_"), clean_metadata.keys())
                ):
                    trace_params[key.replace("trace_", "")] = clean_metadata.pop(
                        key, None
                    )

                if level == "ERROR":
                    trace_params["status_message"] = output
                else:
                    trace_params["output"] = output

            if debug == True or (isinstance(debug, str) and debug.lower() == "true"):
                if "metadata" in trace_params:
                    # log the raw_metadata in the trace
                    trace_params["metadata"]["metadata_passed_to_litellm"] = metadata
                else:
                    trace_params["metadata"] = {"metadata_passed_to_litellm": metadata}

            cost = kwargs.get("response_cost", None)
            print_verbose(f"trace: {cost}")

            if (
                litellm._langfuse_default_tags is not None
                and isinstance(litellm._langfuse_default_tags, list)
                and "proxy_base_url" in litellm._langfuse_default_tags
            ):
                proxy_base_url = os.environ.get("PROXY_BASE_URL", None)
                if proxy_base_url is not None:
                    tags.append(f"proxy_base_url:{proxy_base_url}")

            api_base = litellm_params.get("api_base", None)
            if api_base:
                clean_metadata["api_base"] = api_base

            vertex_location = kwargs.get("vertex_location", None)
            if vertex_location:
                clean_metadata["vertex_location"] = vertex_location

            aws_region_name = kwargs.get("aws_region_name", None)
            if aws_region_name:
                clean_metadata["aws_region_name"] = aws_region_name

            if supports_tags:
                if "cache_hit" in kwargs:
                    if kwargs["cache_hit"] is None:
                        kwargs["cache_hit"] = False
                    tags.append(f"cache_hit:{kwargs['cache_hit']}")
                    clean_metadata["cache_hit"] = kwargs["cache_hit"]
                if existing_trace_id is None:
                    trace_params.update({"tags": tags})

            proxy_server_request = litellm_params.get("proxy_server_request", None)
            if proxy_server_request:
                method = proxy_server_request.get("method", None)
                url = proxy_server_request.get("url", None)
                headers = proxy_server_request.get("headers", None)
                clean_headers = {}
                if headers:
                    for key, value in headers.items():
                        # these headers can leak our API keys and/or JWT tokens
                        if key.lower() not in ["authorization", "cookie", "referer"]:
                            clean_headers[key] = value

                clean_metadata["request"] = {
                    "method": method,
                    "url": url,
                    "headers": clean_headers,
                }
            trace = self.Langfuse.trace(**trace_params)

            generation_id = None
            usage = None
            if response_obj is not None and response_obj.get("id", None) is not None:
                generation_id = litellm.utils.get_logging_id(start_time, response_obj)
                usage = {
                    "prompt_tokens": response_obj["usage"]["prompt_tokens"],
                    "completion_tokens": response_obj["usage"]["completion_tokens"],
                    "total_cost": cost if supports_costs else None,
                }
            generation_name = clean_metadata.pop("generation_name", None)
            if generation_name is None:
                # just log `litellm-{call_type}` as the generation name
                generation_name = f"litellm-{kwargs.get('call_type', 'completion')}"

            if response_obj is not None and "system_fingerprint" in response_obj:
                system_fingerprint = response_obj.get("system_fingerprint", None)
            else:
                system_fingerprint = None

            if system_fingerprint is not None:
                optional_params["system_fingerprint"] = system_fingerprint

            generation_params = {
                "name": generation_name,
                "id": clean_metadata.pop("generation_id", generation_id),
                "start_time": start_time,
                "end_time": end_time,
                "model": kwargs["model"],
                "model_parameters": optional_params,
                "input": input,
                "output": output,
                "usage": usage,
                "metadata": clean_metadata,
                "level": level,
                "version": clean_metadata.pop("version", None),
            }

            if supports_prompt:
                generation_params["prompt"] = clean_metadata.pop("prompt", None)

            if output is not None and isinstance(output, str) and level == "ERROR":
                generation_params["status_message"] = output

            if supports_completion_start_time:
                generation_params["completion_start_time"] = kwargs.get(
                    "completion_start_time", None
                )

            generation_client = trace.generation(**generation_params)

            return generation_client.trace_id, generation_id
        except Exception as e:
            verbose_logger.debug(f"Langfuse Layer Error - {traceback.format_exc()}")
            return None, None

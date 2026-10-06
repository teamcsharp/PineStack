import copy
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from station_json import PineJSONResponse, voice_feed_response


class StationJSONTests(unittest.IsolatedAsyncioTestCase):
    def test_normal_payload_retains_native_encoding(self):
        data={'server_ms':1791083311470,'cut_ms':1791083311000,
              'speech':True,'volume':.4,'rows':[{'id':'cue'}]}
        self.assertEqual(PineJSONResponse(data).body,ORJSONResponse(data).body)

    def test_positive_and_negative_oversized_seeds_are_exact_without_mutation(self):
        data={'seed':2**69+123,'negative':-(2**70),'normal':123,
              'nested':({'topic_seed':2**66+9},),'speech':True,'position':1.25}
        original=copy.deepcopy(data)
        with self.assertRaises(TypeError):ORJSONResponse(data)
        wire=json.loads(PineJSONResponse(data).body)
        self.assertEqual(wire['seed'],str(data['seed']))
        self.assertEqual(wire['nested'][0]['topic_seed'],str(2**66+9))
        self.assertEqual(wire['negative'],str(-(2**70)))
        self.assertEqual(wire['normal'],123)
        self.assertIs(wire['speech'],True)
        self.assertEqual(data,original)

    def test_unrelated_encoding_errors_are_not_hidden(self):
        with self.assertRaises(TypeError):PineJSONResponse({'bad':object()})

    async def test_real_feed_route_cannot_be_poisoned_by_one_recovery_seed(self):
        app=FastAPI(default_response_class=PineJSONResponse)
        clips=[{'delivery_id':'a','ts':1000001,'broadcast_ms':1007000,'speech':True,
                'ready_round':{'dialogue_recovery_variant':{'topic_seed':2**69+123}}},
               {'delivery_id':'b','ts':1000002,'broadcast_ms':1017000,'speech':True}]
        @app.get('/api/dj/voice')
        async def voice():return {'server_ms':1000000,'clips':clips,'cut_ms':1000000}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://station') as client:
            response=await client.get('/api/dj/voice')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['clips']),2)
        self.assertEqual(response.json()['clips'][0]['ready_round']['dialogue_recovery_variant']['topic_seed'],str(2**69+123))
        self.assertIsInstance(clips[0]['ready_round']['dialogue_recovery_variant']['topic_seed'],int)

    async def test_real_feed_isolates_one_invalid_clip_and_keeps_other_speech(self):
        app=FastAPI()
        invalid={'delivery_id':'invalid','metadata':object()}
        good={'delivery_id':'good','ready_round':{'seed':2**69+5}}
        payload={'server_ms':1000,'cut_ms':500,'clips':[invalid,good]}
        @app.get('/api/dj/voice')
        async def voice():return voice_feed_response(payload)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://station') as client:
            response=await client.get('/api/dj/voice')
        self.assertEqual(response.status_code,200)
        wire=response.json()
        self.assertEqual([r['delivery_id'] for r in wire['clips']],['good'])
        self.assertEqual(wire['clips'][0]['ready_round']['seed'],str(2**69+5))
        self.assertEqual(wire['feed_error_count'],1)
        self.assertEqual(wire['feed_errors'][0]['delivery_id'],'invalid')
        self.assertEqual(len(payload['clips']),2)
        self.assertIs(payload['clips'][0],invalid)

    def test_feed_encoder_does_not_hide_invalid_global_cursors(self):
        with self.assertRaises((ValueError,TypeError)):
            voice_feed_response({'server_ms':object(),'clips':[{'delivery_id':'good'}]})

    def test_normal_feed_retains_payload_and_stdlib_response_fallback(self):
        from fastapi.responses import JSONResponse
        payload={'server_ms':1000,'clips':[{'delivery_id':'good','speech':True}]}
        self.assertEqual(json.loads(voice_feed_response(payload,JSONResponse).body),payload)


if __name__=='__main__':unittest.main()

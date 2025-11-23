from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.decorators import api_view

# Create your views here.

@api_view(['GET'])

def health(request):
    return Response({
        "status": "ok",
        "service": "checkpoint-backend",
        "app": "core_app"
    })

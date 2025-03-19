from django.shortcuts import render

# Create your views here.
def home(request):
    return render(request,'system/base_structure.html')

def unit(request):
    return render(request,'system/unit.html')

def product(request):
    return render(request,'system/product.html')

def vendor(request):
    return render(request,'system/vendor.html')

def customer(request):
    return render(request,'system/customer.html')
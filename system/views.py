from django.shortcuts import render

# Create your views here.
def home(request):
    return render(request,'system/base_structure.html')

def unit(request):
    return render(request,'system/unit_data.html')

def unit_data(request):
    return render(request,'system/unit_data.html')

def unit_add(request):
    return render(request,'system/unit_add.html')

def product(request):
    return render(request,'system/product_data.html')

def product_data(request):
    return render(request,'system/product_data.html')

def product_add(request):
    return render(request,'system/product_add.html')

def vendor(request):
    return render(request,'system/vendor_data.html')

def vendor_data(request):
    return render(request,'system/vendor_data.html')

def vendor_add(request):
    return render(request,'system/vendor_add.html')

def customer(request):
    return render(request,'system/customer_data.html')

def customer_data(request):
    return render(request,'system/customer_data.html')

def customer_add(request):
    return render(request,'system/customer_add.html')

def purchase(request):
    return render(request,'system/purchase_data.html')

def purchase_data(request):
    return render(request,'system/purchase_data.html')

def purchase_add(request):
    return render(request,'system/purchase_add.html')

def sale(request):
    return render(request,'system/sale_data.html')

def sale_data(request):
    return render(request,'system/sale_data.html')

def sale_add(request):
    return render(request,'system/sale_add.html')

def setting(request):
    return render(request,'system/setting.html')